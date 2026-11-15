"""
HimalWatch — Export Worker JSON Cache

Reads mart_lake_inventory and mart_change_alerts from R2 Parquet,
converts to compact JSON, and uploads to R2 cache/ prefix.

The Cloudflare Worker reads these cache files — no DuckDB in the Worker.

Run after: dbt run && python export_marts.py

Usage:
    python export_worker_json.py
"""
from __future__ import annotations

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
        CacheControl="public, max-age=3600",
    )
    print(f"  Uploaded cache -> {key} ({len(body):,} bytes)")


def _gif_lake_ids() -> set:
    """lake_ids that have a growth GIF in R2."""
    ids = set()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="media/lakes/"):
        for obj in page.get("Contents", []):
            parts = obj["Key"].split("/")
            if len(parts) == 4 and parts[3] == "growth.gif":
                ids.add(parts[2])
    return ids


def _news() -> dict:
    """{lake_id: [{title, url, source, date}]} from pipeline/news/lake_news.py, if it has run."""
    try:
        news = json.loads(s3.get_object(Bucket=bucket, Key="news/lakes.json")["Body"].read())
        return {k: v for k, v in news.items() if not k.startswith("_")}
    except Exception:  # noqa: BLE001
        return {}


def build_lakes_geojson(inv: pd.DataFrame, linked: pd.DataFrame, gif_ids: set,
                        news: dict | None = None) -> dict:
    """Convert inventory DataFrame to GeoJSON FeatureCollection."""
    # Real per-season history: {lake_id: [[year, area_ha], ...]}
    series = {
        lake_id: [[int(y), round(float(a), 2)] for y, a in
                  zip(g["detection_year"], g["area_ha"])]
        for lake_id, g in linked.sort_values("detection_year").groupby("lake_id")
    }
    features = []
    for _, row in inv.iterrows():
        props = {k: (None if pd.isna(v) else v)
                 for k, v in row.items()
                 if k != "geometry_wkt"}
        props["series"]  = series.get(row["lake_id"], [])
        props["has_gif"] = row["lake_id"] in gif_ids
        if news and news.get(row["lake_id"]):
            props["news"] = news[row["lake_id"]]
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
    linked = _download_parquet("linked/lake_detections.parquet")
    gif_ids = _gif_lake_ids()
    print(f"  {len(inv)} lakes, {len(alerts)} alerts, {len(gif_ids)} GIFs")

    print("Building JSON cache files ...")
    _upload_json("cache/lakes.json",  build_lakes_geojson(inv, linked, gif_ids, _news()))
    _upload_json("cache/alerts.json", build_alerts_json(alerts))
    _upload_json("cache/stats.json",  build_stats_json(inv, alerts))

    print("Worker JSON cache updated.")
