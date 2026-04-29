"""
HimalWatch — Glacial Lake Detection (Python / geemap)

Processes one AOI tile per invocation. Designed to run as a parallel matrix
job in GitHub Actions — each tile is fully independent.

Usage:
    python lake_detection.py --tile khumbu --year 2024
    python lake_detection.py --tile khumbu --year 2024 --output-dir ./outputs --export-r2

Outputs written to {output_dir}/{tile}/:
    lakes_{year}.geojson
    lakes_{year}.parquet    (geometry as WKT, readable by DuckDB)
    lakes_{year}.csv        (no geometry, centroid + attributes only)
    run_log.json            (summary for GitHub Actions artifact)
"""

import argparse
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import ee
import geopandas as gpd
import pandas as pd
import requests
from dotenv import load_dotenv
from shapely.geometry import shape

from cloud_masking import prepare_s2_collection, water_not_snow_mask
from export_to_r2 import upload_all, update_lakes_master

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.aoi_tiles import get_tile_bbox
from utils.volume_estimate import estimate_volume_m3

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NDWI_THRESHOLD   = 0.3       # McFeeters (1996)
ELEV_MIN_M       = 3500      # Below this elevation → not a glacial lake
MIN_AREA_SQM     = 10_000    # 1 hectare minimum
SEASON_START_MM  = "06-01"
SEASON_END_MM    = "09-30"

# Timeout-avoidance settings
DETECT_SCALE_M   = 20        # 20m instead of 10m → 4× fewer pixels, same ha-scale accuracy
MAX_STRIP_DEG    = 1.2       # Split tiles wider than this into longitude strips

# ---------------------------------------------------------------------------
# GEE authentication
# ---------------------------------------------------------------------------

def authenticate_gee(project: str):
    """
    Authenticate using service account key (CI) or user credentials (local).
    CI: GEE_SERVICE_ACCOUNT_KEY env var holds base64-encoded JSON key.
    Local: falls back to earthengine authenticate credentials.
    """
    key_b64 = os.getenv("GEE_SERVICE_ACCOUNT_KEY")
    if key_b64:
        import base64, tempfile
        key_json = base64.b64decode(key_b64).decode()
        key_data = json.loads(key_json)
        credentials = ee.ServiceAccountCredentials(
            email=key_data["client_email"],
            key_data=key_json,
        )
        ee.Initialize(credentials=credentials, project=project)
    else:
        ee.Initialize(project=project)


# ---------------------------------------------------------------------------
# GEE download helpers (timeout-safe)
# ---------------------------------------------------------------------------

def _download_fc(fc: ee.FeatureCollection, label: str = "") -> gpd.GeoDataFrame:
    """
    Download a FeatureCollection to a GeoDataFrame without hitting the
    5-minute synchronous getInfo() timeout.

    Strategy:
      1. Use fc.getDownloadURL(filetype='GEO_JSON') — GEE generates a
         signed download URL asynchronously; we then fetch it with requests.
         This sidesteps the getInfo() timeout entirely.
      2. If that fails (e.g. too many features), fall back to geemap.ee_to_gdf()
         which pages via getInfo().
    """
    try:
        print(f"  [{label}] Requesting GEE download URL ...")
        url = fc.getDownloadURL(filetype="GEO_JSON")
        print(f"  [{label}] Downloading GeoJSON ...")
        resp = requests.get(url, timeout=600)
        resp.raise_for_status()
        geojson = resp.json()
        features = geojson.get("features") or []
        if not features:
            return gpd.GeoDataFrame()
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        print(f"  [{label}] Downloaded {len(gdf)} features via URL")
        return gdf
    except Exception as exc:
        print(f"  [{label}] getDownloadURL failed ({exc}); falling back to geemap ...")
        import geemap  # noqa: PLC0415
        gdf = geemap.ee_to_gdf(fc)
        print(f"  [{label}] Downloaded {len(gdf)} features via geemap")
        return gdf


def _detect_in_strip(
    strip_bbox: tuple,
    tile: str,
    year: int,
    composite,
    dem,
    ndwi,
    ndsi,
    start: str,
    end: str,
    strip_idx: int,
) -> gpd.GeoDataFrame:
    """
    Run lake detection for one longitude strip of a tile.
    Called once per strip; results are concatenated in detect_lakes().
    """
    aoi = ee.Geometry.Rectangle(strip_bbox)
    label = f"{tile}/strip{strip_idx}"

    water_mask = water_not_snow_mask(composite)
    elev_mask  = dem.gt(ELEV_MIN_M)
    final_mask = water_mask.And(elev_mask).selfMask()

    print(f"  [{label}] Vectorising (scale={DETECT_SCALE_M}m) ...")
    lakes_fc = final_mask.reduceToVectors(
        geometry=aoi,
        scale=DETECT_SCALE_M,
        geometryType="polygon",
        eightConnected=False,
        maxPixels=1e9,
        bestEffort=True,
    )

    # Filter by minimum area
    lakes_fc = lakes_fc.map(lambda f: f.set("area_sqm", f.geometry().area(1)))
    lakes_fc = lakes_fc.filter(ee.Filter.gte("area_sqm", MIN_AREA_SQM))

    # Simplify geometries to reduce transfer payload (~20m tolerance)
    lakes_fc = lakes_fc.map(lambda f: f.setGeometry(f.geometry().simplify(DETECT_SCALE_M)))

    # Add per-lake attributes
    def add_attributes(f):
        geom     = f.geometry()
        centroid = geom.centroid(1).coordinates()
        return f.set({
            "centroid_lon":   centroid.get(0),
            "centroid_lat":   centroid.get(1),
            "mean_elevation": dem.reduceRegion(
                ee.Reducer.mean(), geom, 30).get("elevation"),
            "mean_ndwi":      ndwi.reduceRegion(
                ee.Reducer.mean(), geom, DETECT_SCALE_M).get("NDWI"),
            "mean_ndsi":      ndsi.reduceRegion(
                ee.Reducer.mean(), geom, DETECT_SCALE_M).get("NDSI"),
            "detection_year": year,
            "season_start":   start,
            "season_end":     end,
            "tile":           tile,
        })

    lakes_fc = lakes_fc.map(add_attributes)

    return _download_fc(lakes_fc, label=label)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_lakes(tile: str, year: int) -> gpd.GeoDataFrame:
    """
    Run lake detection for one tile and year. Returns a GeoDataFrame.

    Steps:
      1. Build cloud-free S2 composite for the tile/season
      2. Apply water + snow discrimination mask
      3. Split wide tiles into longitude strips (avoids GEE timeout)
      4. Per strip: vectorise → filter by area → add attributes → download
      5. Merge strips, derive columns
    """
    bbox = get_tile_bbox(tile)
    min_lon, min_lat, max_lon, max_lat = bbox

    start = f"{year}-{SEASON_START_MM}"
    end   = f"{year}-{SEASON_END_MM}"

    # Build composite once over the full tile AOI
    full_aoi = ee.Geometry.Rectangle(bbox)
    print(f"[{tile}] Building S2 composite {start} -> {end} ...")
    composite = prepare_s2_collection(full_aoi, start, end, composite_method="median")
    dem  = ee.Image("USGS/SRTMGL1_003").select("elevation")
    ndwi = composite.select("NDWI")
    ndsi = composite.select("NDSI")

    # Split into longitude strips for wide tiles
    tile_width = max_lon - min_lon
    n_strips   = max(1, math.ceil(tile_width / MAX_STRIP_DEG))
    strip_w    = tile_width / n_strips
    strips = [
        (min_lon + i * strip_w, min_lat, min_lon + (i + 1) * strip_w, max_lat)
        for i in range(n_strips)
    ]
    if n_strips > 1:
        print(f"[{tile}] Splitting into {n_strips} longitude strips "
              f"(tile width={tile_width:.2f}°, max={MAX_STRIP_DEG}°)")

    gdfs = []
    for i, strip_bbox in enumerate(strips):
        gdf_strip = _detect_in_strip(
            strip_bbox=strip_bbox,
            tile=tile,
            year=year,
            composite=composite,
            dem=dem,
            ndwi=ndwi,
            ndsi=ndsi,
            start=start,
            end=end,
            strip_idx=i,
        )
        if not gdf_strip.empty:
            gdfs.append(gdf_strip)

    if not gdfs:
        print(f"[{tile}] WARNING: No lakes detected in any strip. "
              "Check cloud cover or season.")
        return gpd.GeoDataFrame()

    gdf = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs="EPSG:4326")

    # Ensure area_sqm column exists (populated from GEE properties)
    if "area_sqm" not in gdf.columns:
        gdf["area_sqm"] = gdf.geometry.area  # fallback (projected units — rough)

    # Derive output columns
    gdf["area_ha"]    = gdf["area_sqm"] / 10_000
    gdf["volume_m3"]  = gdf["area_sqm"].apply(estimate_volume_m3)
    gdf["volume_mcm"] = gdf["volume_m3"] / 1_000_000
    gdf["detected_at"] = datetime.now(timezone.utc).isoformat()

    print(f"[{tile}] Detected {len(gdf)} lakes, "
          f"total area {gdf['area_sqm'].sum() / 1e6:.2f} sqkm")

    return gdf


# ---------------------------------------------------------------------------
# Stable lake_id assignment
# ---------------------------------------------------------------------------

def assign_lake_ids(gdf: gpd.GeoDataFrame, master_path: Path) -> gpd.GeoDataFrame:
    """
    Assign stable lake_ids by spatial join against the master lake registry.

    For each new detection:
      - If a lake exists in master within 50m of centroid → use its lake_id
      - Otherwise → assign new UUID and add to master

    The 50m tolerance (5 S2 pixels) accounts for inter-annual centroid drift
    caused by varying water levels and cloud coverage patterns.
    """
    # Build centroid GeoDataFrame for spatial join
    centroids = gdf.copy()
    centroids = centroids.to_crs("EPSG:32645")  # UTM Zone 45N covers Nepal
    centroids.geometry = centroids.geometry.centroid

    if master_path.exists():
        master_df = pd.read_parquet(master_path)
        master_pts = gpd.GeoDataFrame(
            master_df,
            geometry=gpd.GeoSeries.from_wkt(master_df["centroid_wkt"], crs="EPSG:4326"),
        ).to_crs("EPSG:32645")

        # Spatial join with 50m buffer
        joined = gpd.sjoin_nearest(
            centroids,
            master_pts[["lake_id", "geometry"]],
            how="left",
            max_distance=50,
            distance_col="match_dist_m",
        )
        gdf["lake_id"] = joined["lake_id"].values

    else:
        gdf["lake_id"] = None

    # New lakes get a fresh UUID
    new_mask = gdf["lake_id"].isna()
    gdf.loc[new_mask, "lake_id"] = [str(uuid.uuid4())[:8] for _ in range(new_mask.sum())]

    new_count = new_mask.sum()
    if new_count:
        print(f"  {new_count} new lakes assigned IDs (not in master)")

    return gdf


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def save_outputs(gdf: gpd.GeoDataFrame, tile: str, year: int, output_dir: Path):
    """Write GeoJSON, Parquet (geometry as WKT), and CSV to output_dir."""
    out = output_dir / tile
    out.mkdir(parents=True, exist_ok=True)

    # GeoJSON
    geojson_path = out / f"lakes_{year}.geojson"
    gdf.to_file(geojson_path, driver="GeoJSON")

    # Parquet — geometry as WKT so DuckDB can read without spatial extension
    parquet_path = out / f"lakes_{year}.parquet"
    df_parquet = gdf.copy()
    df_parquet["geometry_wkt"] = df_parquet.geometry.to_wkt()
    df_parquet = df_parquet.drop(columns=["geometry"])
    df_parquet.to_parquet(parquet_path, index=False)

    # CSV — no geometry, centroid + attributes
    csv_path = out / f"lakes_{year}.csv"
    csv_cols = [
        "lake_id", "tile", "detection_year", "season_start", "season_end",
        "centroid_lat", "centroid_lon", "area_sqm", "area_ha",
        "mean_elevation", "mean_ndwi", "mean_ndsi",
        "volume_m3", "volume_mcm", "detected_at",
    ]
    gdf[csv_cols].to_csv(csv_path, index=False)

    return geojson_path, parquet_path, csv_path


def write_run_log(
    tile: str, year: int, lake_count: int,
    total_area_sqkm: float, status: str, output_dir: Path
):
    log = {
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "tile":            tile,
        "year":            year,
        "lakes_detected":  lake_count,
        "total_area_sqkm": round(total_area_sqkm, 4),
        "status":          status,
    }
    log_path = output_dir / tile / "run_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2))
    return log


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HimalWatch lake detection pipeline")
    parser.add_argument("--tile",       required=True,
                        help="AOI tile name (e.g. khumbu, langtang)")
    parser.add_argument("--year",       type=int,
                        default=datetime.now().year - 1,
                        help="Year to process (default: last complete year)")
    parser.add_argument("--output-dir", type=Path, default=Path("./outputs"),
                        help="Local directory for outputs")
    parser.add_argument("--export-r2",  action="store_true",
                        help="Upload outputs to Cloudflare R2 after detection")
    args = parser.parse_args()

    project = os.getenv("GEE_PROJECT", "himalwatch")
    print(f"Initialising GEE (project: {project}) ...")
    authenticate_gee(project)

    master_path = args.output_dir / "lakes_master.parquet"

    try:
        gdf = detect_lakes(args.tile, args.year)

        if not gdf.empty:
            gdf = assign_lake_ids(gdf, master_path)
            geojson_path, parquet_path, csv_path = save_outputs(
                gdf, args.tile, args.year, args.output_dir
            )
            print(f"Outputs written to {args.output_dir / args.tile}/")

            if args.export_r2:
                print("Uploading to R2 ...")
                upload_all(geojson_path, parquet_path, csv_path, args.tile, args.year)
                update_lakes_master(gdf, master_path)
                print("R2 upload complete.")

        log = write_run_log(
            tile=args.tile,
            year=args.year,
            lake_count=len(gdf),
            total_area_sqkm=gdf["area_sqm"].sum() / 1e6 if not gdf.empty else 0.0,
            status="success",
            output_dir=args.output_dir,
        )
        print(f"\n=== Run complete ===")
        print(json.dumps(log, indent=2))

    except Exception as exc:
        write_run_log(args.tile, args.year, 0, 0.0, f"error: {exc}", args.output_dir)
        raise


if __name__ == "__main__":
    main()
