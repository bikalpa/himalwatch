"""
Export dbt mart tables from local DuckDB to Cloudflare R2.
Run after: dbt run

Usage:
    python export_marts.py
"""
import os
import tempfile
from pathlib import Path

import boto3
import duckdb
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
db     = Path(__file__).parent / "himalwatch_dev.duckdb"

con = duckdb.connect(str(db))

exports = [
    ("mart_lake_inventory", "marts/mart_lake_inventory.parquet"),
    ("mart_change_alerts",  "marts/mart_change_alerts.parquet"),
]

for table, r2_key in exports:
    local = tmp / f"{table}.parquet"
    # DuckDB needs forward slashes even on Windows
    con.execute(f"COPY {table} TO '{local.as_posix()}' (FORMAT PARQUET)")
    s3.upload_file(str(local), bucket, r2_key)
    size = local.stat().st_size
    print(f"  Uploaded {table} -> {r2_key} ({size:,} bytes)")

con.close()

# Also write a timestamped snapshot
import datetime
date_str = datetime.date.today().isoformat()
for table, _ in exports:
    local    = tmp / f"{table}.parquet"
    snap_key = f"marts/snapshots/{date_str}/{table}.parquet"
    s3.upload_file(str(local), bucket, snap_key)
    print(f"  Snapshot  {table} -> {snap_key}")

print("Export complete.")
