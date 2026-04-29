"""
HimalWatch — Export Worker JSON Cache

Reads mart_lake_inventory and mart_change_alerts from R2 Parquet,
converts to compact JSON, and uploads to R2 cache/ prefix.

The Cloudflare Worker reads these cache files — no DuckDB in the Worker.

Run after: dbt run && python export_marts.py

Usage:
    python export_worker_json.py
"""
import io
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import boto3
import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["R2_ENDPOINT_URL"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
)
bucket = os.getenv("R2_BUCKET_NAME", "himalwatch-data")
tmp    = Path(tempfile.gettempdir())


def _download_parquet(key: str) -> pd.DataFrame:
    buf = io.BytesIO()
    s3.download_fileobj(bucket, key, buf)
    buf.seek(0)
    return pd.read_parquet(buf)


def _upload_json(key: str, data: dict):
    body = json.dumps(data, default=str).encode()
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        CacheControl="public, max-age=21600",  # 6h
    )
    print(f"  Uploaded cache -> {key} ({len(body):,} bytes)")


def build_lakes_geojson(inv: pd.DataFrame) -> dict:
    """Convert inventory DataFrame to GeoJSON FeatureCollection."""
    features = []
    for _, row in inv.iterrows():
        props = {k: (None if pd.isna(v) else v)
                 for k, v in row.items()
                 if k != "geometry_wkt"}
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row["centroid_lon"], row["centroid_lat"]],
            },
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}


def build_alerts_json(alerts: pd.DataFrame) -> dict:
    """Convert alerts DataFrame to list of dicts."""
    return {
        "alerts": [
            {k: (None if pd.isna(v) else v) for k, v in row.items()}
            for _, row in alerts.iterrows()
        ]
    }


def build_stats_json(inv: pd.DataFrame, alerts: pd.DataFrame) -> dict:
    """Aggregate stats for the API root and dashboard header."""
    return {
        "total_lakes":          len(inv),
        "total_water_area_sqkm": round(inv["latest_area_sqm"].sum() / 1e6, 3),
        "total_volume_mcm":     round(inv["latest_volume_mcm"].sum(), 2),
        "lakes_with_alerts":    inv["alert_severity"].notna().sum(),
        "high_severity_count":  (inv["alert_severity"] == "HIGH").sum(),
        "medium_severity_count":(inv["alert_severity"] == "MEDIUM").sum(),
        "low_severity_count":   (inv["alert_severity"] == "LOW").sum(),
        "tiles_covered":        inv["tile"].nunique(),
        "tiles":                sorted(inv["tile"].unique().tolist()),
        "last_pipeline_run":    datetime.now(timezone.utc).isoformat(),
        "detection_year_range": {
            "min": int(inv["first_detected_date"].astype(str).str[:4].min()),
            "max": int(inv["latest_detection_date"].astype(str).str[:4].max()),
        } if len(inv) > 0 else {},
    }


if __name__ == "__main__":
    print("Downloading mart tables from R2 ...")
    inv    = _download_parquet("marts/mart_lake_inventory.parquet")
    alerts = _download_parquet("marts/mart_change_alerts.parquet")
    print(f"  {len(inv)} lakes, {len(alerts)} alerts")

    print("Building JSON cache files ...")
    _upload_json("cache/lakes.json",  build_lakes_geojson(inv))
    _upload_json("cache/alerts.json", build_alerts_json(alerts))
    _upload_json("cache/stats.json",  build_stats_json(inv, alerts))

    print("Worker JSON cache updated.")
