"""
HimalWatch — Upload Pipeline Outputs to Cloudflare R2

Cloudflare R2 is S3-compatible. All uploads go via boto3 with a custom
endpoint_url. Geometry is stored as WKT strings so DuckDB can read Parquet
files without requiring the spatial extension.

R2 path layout:
    raw/lakes/{tile}/{year}/lakes.geojson
    raw/lakes/{tile}/{year}/lakes.parquet
    raw/lakes/{tile}/{year}/lakes.csv
    raw/metadata/lakes_master.parquet   ← stable lake_id registry

Config via environment variables (load from .env locally, secrets in CI):
    R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME
"""

import io
import os
from pathlib import Path
from typing import List, Optional

import boto3
import geopandas as gpd
import pandas as pd
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# S3 client
# ---------------------------------------------------------------------------

def _client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )

def _bucket() -> str:
    return os.getenv("R2_BUCKET_NAME", "himalwatch-data")


# ---------------------------------------------------------------------------
# Individual upload functions
# ---------------------------------------------------------------------------

def upload_geojson(local_path: Path, tile: str, year: int):
    """Upload GeoJSON to raw/lakes/{tile}/{year}/lakes.geojson"""
    key = f"raw/lakes/{tile}/{year}/lakes.geojson"
    _client().upload_file(
        str(local_path), _bucket(), key,
        ExtraArgs={"ContentType": "application/geo+json"},
    )
    print(f"  Uploaded -> {key}")


def upload_parquet(local_path: Path, tile: str, year: int):
    """Upload Parquet to raw/lakes/{tile}/{year}/lakes.parquet"""
    key = f"raw/lakes/{tile}/{year}/lakes.parquet"
    _client().upload_file(
        str(local_path), _bucket(), key,
        ExtraArgs={"ContentType": "application/octet-stream"},
    )
    print(f"  Uploaded -> {key}")


def upload_csv(local_path: Path, tile: str, year: int):
    """Upload CSV to raw/lakes/{tile}/{year}/lakes.csv"""
    key = f"raw/lakes/{tile}/{year}/lakes.csv"
    _client().upload_file(
        str(local_path), _bucket(), key,
        ExtraArgs={"ContentType": "text/csv"},
    )
    print(f"  Uploaded -> {key}")


def upload_all(
    geojson_path: Path,
    parquet_path: Path,
    csv_path: Path,
    tile: str,
    year: int,
):
    """Convenience: upload all three output files for a tile/year."""
    upload_geojson(geojson_path, tile, year)
    upload_parquet(parquet_path, tile, year)
    upload_csv(csv_path, tile, year)


# ---------------------------------------------------------------------------
# Lakes master — stable lake_id registry
# ---------------------------------------------------------------------------

MASTER_KEY = "raw/metadata/lakes_master.parquet"


def _download_master() -> Optional[gpd.GeoDataFrame]:
    """Download lakes_master.parquet from R2. Returns None if it doesn't exist yet."""
    buf = io.BytesIO()
    try:
        _client().download_fileobj(_bucket(), MASTER_KEY, buf)
        buf.seek(0)
        df = pd.read_parquet(buf)
        gdf = gpd.GeoDataFrame(
            df,
            geometry=gpd.GeoSeries.from_wkt(df["centroid_wkt"], crs="EPSG:4326"),
        )
        return gdf
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def _upload_master(gdf: gpd.GeoDataFrame):
    """Upload updated lakes_master.parquet to R2."""
    df = gdf.copy()
    df["centroid_wkt"] = df.geometry.to_wkt()
    df = df.drop(columns=["geometry"])

    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)

    _client().upload_fileobj(
        buf, _bucket(), MASTER_KEY,
        ExtraArgs={"ContentType": "application/octet-stream"},
    )
    print(f"  Updated master registry -> {MASTER_KEY} ({len(df)} lakes total)")


def update_lakes_master(new_detections: gpd.GeoDataFrame, local_cache: Path):
    """
    Merge new detections into the master lake registry on R2.

    The master holds one row per unique lake_id with its canonical centroid.
    New lake_ids from new_detections are appended; existing ones are not updated
    (centroid stability is the point — the master is the source of truth).

    Also saves a local cache of the master for the spatial join in lake_detection.py.
    """
    master = _download_master()

    # Build master entry from new detections: one row per lake_id
    new_rows = new_detections[["lake_id", "centroid_lat", "centroid_lon", "tile"]].copy()
    new_rows["centroid_wkt"] = new_detections.geometry.to_crs("EPSG:32645").centroid.to_crs("EPSG:4326").to_wkt()
    new_rows_gdf = gpd.GeoDataFrame(
        new_rows,
        geometry=gpd.GeoSeries.from_wkt(new_rows["centroid_wkt"], crs="EPSG:4326"),
    )

    if master is None:
        updated = new_rows_gdf
    else:
        # Only append lake_ids not already in master
        existing_ids = set(master["lake_id"])
        to_add = new_rows_gdf[~new_rows_gdf["lake_id"].isin(existing_ids)]
        updated = pd.concat([master, to_add], ignore_index=True)
        updated = gpd.GeoDataFrame(updated, geometry="geometry", crs="EPSG:4326")

    _upload_master(updated)

    # Save local cache for next run's spatial join
    local_cache.parent.mkdir(parents=True, exist_ok=True)
    cache_df = updated.copy()
    cache_df["centroid_wkt"] = cache_df.geometry.to_wkt()
    cache_df.drop(columns=["geometry"]).to_parquet(local_cache, index=False)


# ---------------------------------------------------------------------------
# Utility: list what's already in R2
# ---------------------------------------------------------------------------

def list_available_tiles_years() -> List[dict]:
    """Return list of {tile, year} dicts for data already in R2."""
    s3 = _client()
    paginator = s3.get_paginator("list_objects_v2")
    results = []

    for page in paginator.paginate(Bucket=_bucket(), Prefix="raw/lakes/", Delimiter="/"):
        for prefix in page.get("CommonPrefixes", []):
            # prefix looks like "raw/lakes/khumbu/"
            tile = prefix["Prefix"].split("/")[2]
            year_pages = s3.get_paginator("list_objects_v2").paginate(
                Bucket=_bucket(),
                Prefix=f"raw/lakes/{tile}/",
                Delimiter="/",
            )
            for ypage in year_pages:
                for yprefix in ypage.get("CommonPrefixes", []):
                    year = yprefix["Prefix"].split("/")[3]
                    results.append({"tile": tile, "year": int(year)})

    return results


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Run connection smoke test")
    parser.add_argument("--list", action="store_true", help="List available data in R2")
    args = parser.parse_args()

    if args.test:
        print("Running R2 smoke test ...")
        s3 = _client()
        test_key = "test/smoke_test.txt"
        s3.put_object(Bucket=_bucket(), Key=test_key, Body=b"himalwatch-ok")
        obj = s3.get_object(Bucket=_bucket(), Key=test_key)
        assert obj["Body"].read() == b"himalwatch-ok"
        s3.delete_object(Bucket=_bucket(), Key=test_key)
        print("R2 smoke test passed.")

    if args.list:
        tiles_years = list_available_tiles_years()
        if tiles_years:
            for entry in tiles_years:
                print(f"  {entry['tile']} / {entry['year']}")
        else:
            print("No data in R2 yet.")
