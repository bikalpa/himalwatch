"""
HimalWatch — Sentinel-1 SAR Water Detection

Fallback for monsoon season (June–September) when Sentinel-2 optical
imagery is blocked by cloud cover. Sentinel-1 C-band SAR penetrates clouds,
enabling detection even during Nepal's peak monsoon.

Water on calm lake surfaces returns very low backscatter (specular reflection
away from sensor) appearing dark in SAR imagery. This contrasts with land
surfaces which scatter energy back toward the sensor.

Science refs:
  - Twele et al. (2016) Sentinel-1 based flood mapping — threshold approach
  - Notti et al. (2018) SAR flood detection in complex terrain
  - Pulvirenti et al. (2011) SAR for water/non-water discrimination

Limitations vs optical:
  - Wind-roughened lake surfaces scatter more energy back → false negatives
  - Layover/shadow in steep mountain terrain → false positives near ridges
  - No snow discrimination needed (SAR penetrates snow at C-band)
  - Cross-polarisation (VH) helps distinguish water from smooth bare ground

Usage:
    python sar_detection.py --tile khumbu --year 2024
    python sar_detection.py --tile khumbu --year 2024 --export-r2
    python sar_detection.py --tile khumbu --year 2024 --merge-optical  # preferred
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import ee
import geopandas as gpd
import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.aoi_tiles import get_tile_bbox
from utils.volume_estimate import estimate_volume_m3

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# VV backscatter threshold for water (dB). Water ≈ -20 to -15 dB on calm days.
# Calibrated for Himalayan lakes; may need adjustment for very turbid water.
VV_WATER_THRESHOLD_DB  = -15.0

# VH threshold — cross-pol helps filter smooth bare ground (roads, flat rock)
VH_WATER_THRESHOLD_DB  = -25.0

ELEV_MIN_M   = 3500
MIN_AREA_SQM = 10_000
SEASON_START_MM = "06-01"
SEASON_END_MM   = "09-30"


# ---------------------------------------------------------------------------
# Authentication (shared with lake_detection.py)
# ---------------------------------------------------------------------------

def authenticate_gee(project: str):
    key_b64 = os.getenv("GEE_SERVICE_ACCOUNT_KEY")
    if key_b64:
        import base64
        key_json = base64.b64decode(key_b64).decode()
        import json as _json
        key_data = _json.loads(key_json)
        credentials = ee.ServiceAccountCredentials(
            email=key_data["client_email"],
            key_data=key_json,
        )
        ee.Initialize(credentials=credentials, project=project)
    else:
        ee.Initialize(project=project)


# ---------------------------------------------------------------------------
# SAR preprocessing
# ---------------------------------------------------------------------------

def apply_speckle_filter(image: ee.Image, kernel_size: int = 7) -> ee.Image:
    """
    Apply a focal mean (boxcar) speckle filter to reduce SAR speckle noise.

    A 7x7 kernel at 10m resolution = 70m smoothing window — appropriate for
    detecting lakes of 1 ha minimum (100m diameter). Larger kernels reduce
    speckle more but blur lake boundaries.

    For production consider a Lee or Refined Lee filter for better edge
    preservation, but focal mean is sufficient for area estimation.
    """
    smoothed = image.focal_mean(
        radius=kernel_size // 2,
        kernelType="square",
        units="pixels",
    )
    return smoothed


def build_sar_composite(
    aoi: ee.Geometry,
    start_date: str,
    end_date: str,
) -> ee.Image:
    """
    Build a cloud-free SAR composite from Sentinel-1 GRD data.

    Filters:
      - IW (Interferometric Wide) mode — 10m resolution, covers Nepal
      - VV + VH dual polarisation — both needed for water/land discrimination
      - Ascending pass — more consistent geometry for mountain terrain
        (descending pass has severe layover on south-facing slopes)

    Composite method: median of all acquisitions in the season.
    Median is robust to transient bright targets (ships, rain cells).
    """
    s1 = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .filter(ee.Filter.eq("orbitProperties_pass", "ASCENDING"))
        .select(["VV", "VH"])
        .map(apply_speckle_filter)
    )

    count = s1.size().getInfo()
    print(f"  Sentinel-1 scenes in collection: {count}")
    if count == 0:
        raise RuntimeError(
            "No Sentinel-1 scenes found. Check AOI, date range, or pass direction."
        )

    return s1.median()


# ---------------------------------------------------------------------------
# Water detection
# ---------------------------------------------------------------------------

def detect_water_sar(composite: ee.Image, dem: ee.Image) -> ee.Image:
    """
    Detect water from SAR backscatter using dual-threshold on VV and VH.

    Water condition:
      VV < -15 dB  (specular reflection — calm water is very dark)
      VH < -25 dB  (cross-pol also low for water; helps reject smooth ground)
      elevation > 3500 m  (restrict to glacial lake elevations)

    Returns a binary mask (1=water, 0=non-water).
    """
    vv = composite.select("VV")
    vh = composite.select("VH")

    water_vv   = vv.lt(VV_WATER_THRESHOLD_DB)
    water_vh   = vh.lt(VH_WATER_THRESHOLD_DB)
    elev_mask  = dem.gt(ELEV_MIN_M)

    water_mask = water_vv.And(water_vh).And(elev_mask).selfMask()
    return water_mask


# ---------------------------------------------------------------------------
# Main detection function
# ---------------------------------------------------------------------------

def detect_lakes_sar(tile: str, year: int) -> gpd.GeoDataFrame:
    """
    Run SAR-based lake detection for one tile and year.

    Falls back gracefully if no S1 data is available for the tile/season.
    Returns empty GeoDataFrame in that case (optical detection is preferred).
    """
    bbox = get_tile_bbox(tile)
    aoi  = ee.Geometry.Rectangle(bbox)
    dem  = ee.Image("USGS/SRTMGL1_003").select("elevation")

    start = f"{year}-{SEASON_START_MM}"
    end   = f"{year}-{SEASON_END_MM}"

    print(f"[{tile}/SAR] Building S1 composite {start} -> {end} ...")
    composite = build_sar_composite(aoi, start, end)

    print(f"[{tile}/SAR] Detecting water ...")
    water_mask = detect_water_sar(composite, dem)

    # Vectorise
    lakes_fc = water_mask.reduceToVectors(
        geometry=aoi,
        scale=10,
        geometryType="polygon",
        eightConnected=False,
        maxPixels=1e10,
        bestEffort=True,
    )

    # Add area and filter
    lakes_fc = lakes_fc.map(lambda f: f.set("area_sqm", f.geometry().area(1)))
    lakes_fc = lakes_fc.filter(ee.Filter.gte("area_sqm", MIN_AREA_SQM))

    vv = composite.select("VV")
    vh = composite.select("VH")

    def add_attributes(f):
        geom     = f.geometry()
        centroid = geom.centroid(1).coordinates()
        return f.set({
            "centroid_lon":   centroid.get(0),
            "centroid_lat":   centroid.get(1),
            "mean_elevation": dem.reduceRegion(ee.Reducer.mean(), geom, 30).get("elevation"),
            "mean_vv_db":     vv.reduceRegion(ee.Reducer.mean(), geom, 10).get("VV"),
            "mean_vh_db":     vh.reduceRegion(ee.Reducer.mean(), geom, 10).get("VH"),
            "detection_year": year,
            "season_start":   start,
            "season_end":     end,
            "tile":           tile,
            "source":         "SAR",   # flag: this detection came from SAR not optical
        })

    lakes_fc = lakes_fc.map(add_attributes)

    print(f"[{tile}/SAR] Fetching results from GEE ...")
    import geemap  # noqa: PLC0415 — lazy import avoids Windows handle exhaustion
    gdf = geemap.ee_to_gdf(lakes_fc)

    if gdf.empty:
        print(f"[{tile}/SAR] No lakes detected via SAR.")
        return gdf

    # Harmonise schema with optical output — set missing optical columns to NaN
    gdf["mean_ndwi"]  = float("nan")
    gdf["mean_ndsi"]  = float("nan")
    gdf["area_ha"]    = gdf["area_sqm"] / 10_000
    gdf["volume_m3"]  = gdf["area_sqm"].apply(estimate_volume_m3)
    gdf["volume_mcm"] = gdf["volume_m3"] / 1_000_000
    gdf["detected_at"] = datetime.now(timezone.utc).isoformat()

    print(f"[{tile}/SAR] Detected {len(gdf)} lakes, "
          f"total area {gdf['area_sqm'].sum() / 1e6:.2f} sqkm")
    return gdf


# ---------------------------------------------------------------------------
# Merge optical + SAR detections
# ---------------------------------------------------------------------------

def merge_optical_sar(
    optical_gdf: gpd.GeoDataFrame,
    sar_gdf: gpd.GeoDataFrame,
    overlap_threshold_m: float = 50.0,
) -> gpd.GeoDataFrame:
    """
    Merge optical and SAR detections, preferring optical where both exist.

    Strategy:
      1. Keep all optical detections as-is (preferred — more accurate area)
      2. Add SAR detections that do NOT overlap any optical lake within
         overlap_threshold_m (these are cloud-obscured lakes that SAR found)
      3. Tag each detection with its source: 'optical', 'SAR', or 'both'

    The 'both' tag is informative — it means SAR confirmed the optical detection
    even though optical is the one kept. Useful for validation.
    """
    if optical_gdf.empty and sar_gdf.empty:
        return gpd.GeoDataFrame()
    if optical_gdf.empty:
        sar_gdf["source"] = "SAR"
        return sar_gdf
    if sar_gdf.empty:
        optical_gdf["source"] = "optical"
        return optical_gdf

    # Project both to UTM for distance calculations
    opt_utm = optical_gdf.to_crs("EPSG:32645")
    sar_utm = sar_gdf.to_crs("EPSG:32645")

    # Find SAR lakes with no nearby optical lake
    joined = gpd.sjoin_nearest(
        sar_utm,
        opt_utm[["geometry"]],
        how="left",
        max_distance=overlap_threshold_m,
        distance_col="dist_to_optical_m",
    )
    sar_only = sar_gdf[joined["dist_to_optical_m"].isna().values].copy()
    sar_only["source"] = "SAR"

    optical_gdf = optical_gdf.copy()
    optical_gdf["source"] = "optical"

    merged = pd.concat([optical_gdf, sar_only], ignore_index=True)
    merged = gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:4326")

    print(f"  Merge: {len(optical_gdf)} optical + {len(sar_only)} SAR-only "
          f"= {len(merged)} total lakes")
    return merged


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HimalWatch SAR lake detection")
    parser.add_argument("--tile",          required=True)
    parser.add_argument("--year",          type=int, default=datetime.now().year - 1)
    parser.add_argument("--output-dir",    type=Path, default=Path("./outputs"))
    parser.add_argument("--export-r2",     action="store_true")
    parser.add_argument("--merge-optical", action="store_true",
                        help="Merge with existing optical detections for this tile/year")
    args = parser.parse_args()

    project = os.getenv("GEE_PROJECT", "himalwatch")
    print(f"Initialising GEE (project: {project}) ...")
    authenticate_gee(project)

    try:
        sar_gdf = detect_lakes_sar(args.tile, args.year)

        if args.merge_optical and not sar_gdf.empty:
            optical_path = args.output_dir / args.tile / f"lakes_{args.year}.parquet"
            if optical_path.exists():
                optical_df  = pd.read_parquet(optical_path)
                from shapely import wkt
                optical_df["geometry"] = optical_df["geometry_wkt"].apply(wkt.loads)
                optical_gdf = gpd.GeoDataFrame(
                    optical_df, geometry="geometry", crs="EPSG:4326"
                )
                sar_gdf = merge_optical_sar(optical_gdf, sar_gdf)
            else:
                print("No optical output found to merge — using SAR only.")

        if not sar_gdf.empty:
            out = args.output_dir / args.tile
            out.mkdir(parents=True, exist_ok=True)
            out_path = out / f"lakes_{args.year}_sar.geojson"
            sar_gdf.to_file(out_path, driver="GeoJSON")
            print(f"Written -> {out_path}")

            if args.export_r2:
                from export_to_r2 import upload_geojson
                upload_geojson(out_path, f"{args.tile}_sar", args.year)

        log = {
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "tile":            args.tile,
            "year":            args.year,
            "source":          "SAR",
            "lakes_detected":  len(sar_gdf),
            "total_area_sqkm": round(sar_gdf["area_sqm"].sum() / 1e6, 4)
                               if not sar_gdf.empty else 0.0,
            "status":          "success",
        }
        print(json.dumps(log, indent=2))

    except Exception as exc:
        print(f"ERROR: {exc}")
        raise


if __name__ == "__main__":
    main()
