"""
HimalWatch — Link lake detections across years

The detection step assigns a fresh random lake_id on every run (each CI runner
starts with no master registry), so the same physical lake had a different id
every year and no area trend could ever be computed.

This step fixes identity after the fact, from geometry alone:

  1. Read every raw/lakes/{tile}/{year}/lakes.parquet from R2.
  2. Within a tile, two detections are the same lake if their polygons
     overlap (any year pair). Connected components of that overlap graph
     are lakes. Overlap is used instead of centroid distance because a
     growing lake moves its own centroid.
  3. lake_id = hash of the component's earliest-year centroid, so ids are
     deterministic and survive re-runs.
  4. One output row per (lake_id, year): polygons of that lake in that year
     are unioned and their areas summed (handles lakes that split or merge).

Output: linked/lake_detections.parquet in R2 — this is what dbt staging reads.

Usage:
    python pipeline/link_lakes.py              # R2 in, R2 out
    python pipeline/link_lakes.py --local-dir ./data --out linked.parquet
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import sys
from pathlib import Path

import pandas as pd
from shapely import wkt
from shapely.ops import unary_union
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).parent))
from utils.volume_estimate import estimate_volume_m3  # noqa: E402

LINKED_KEY = "linked/lake_detections.parquet"
# Ignore sliver contacts: polygons must share at least this fraction of the
# smaller one to count as the same lake.
MIN_OVERLAP_FRAC = 0.10
# Only link detections made with the current method (Sep–Oct composite).
# Older files in R2 used a Jun–Sep window and a broken water test.
SEASON_START_MM = "09-01"


# ---------------------------------------------------------------------------
# Linking (pure — no I/O)
# ---------------------------------------------------------------------------

def _find(parent: list, i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def link_detections(raw: pd.DataFrame) -> pd.DataFrame:
    """
    raw: one row per detected polygon, columns at least
         tile, detection_year, geometry_wkt, area_sqm, mean_elevation,
         mean_ndwi, mean_ndsi, season_start, season_end, detected_at
    Returns one row per (lake_id, detection_year).
    """
    raw = raw[raw["geometry_wkt"].notna() & raw["area_sqm"].notna()].copy()
    raw = raw[raw["season_start"].astype(str).str.endswith(SEASON_START_MM)]
    if raw.empty:
        raise SystemExit(f"No detections for the {SEASON_START_MM} season window yet.")
    raw["detection_year"] = raw["detection_year"].astype(int)
    raw = raw.reset_index(drop=True)
    raw["geom"] = raw["geometry_wkt"].apply(wkt.loads)
    raw["geom"] = raw["geom"].apply(lambda g: g if g.is_valid else g.buffer(0))
    raw = raw[~raw["geom"].apply(lambda g: g.is_empty)].reset_index(drop=True)

    out = []
    for tile, grp in raw.groupby("tile"):
        grp = grp.reset_index(drop=True)
        geoms = grp["geom"].tolist()
        parent = list(range(len(geoms)))
        tree = STRtree(geoms)
        left, right = tree.query(geoms, predicate="intersects")
        for i, j in zip(left, right):
            if i >= j:
                continue
            inter = geoms[i].intersection(geoms[j]).area
            if inter >= MIN_OVERLAP_FRAC * min(geoms[i].area, geoms[j].area):
                parent[_find(parent, i)] = _find(parent, j)
        grp["component"] = [_find(parent, i) for i in range(len(geoms))]

        for _, comp in grp.groupby("component"):
            first_year = comp["detection_year"].min()
            anchor = unary_union(
                comp.loc[comp["detection_year"] == first_year, "geom"].tolist()
            ).centroid
            lake_id = hashlib.sha1(
                f"{tile}:{anchor.y:.4f},{anchor.x:.4f}".encode()
            ).hexdigest()[:8]

            for year, yr in comp.groupby("detection_year"):
                geom = unary_union(yr["geom"].tolist())
                area = float(yr["area_sqm"].sum())
                w = yr["area_sqm"] / area

                def wavg(col):
                    if col not in yr or yr[col].isna().all():
                        return None
                    return float((yr[col].astype(float) * w).sum())

                vol = float(estimate_volume_m3(area))
                out.append({
                    "lake_id":        lake_id,
                    "tile":           tile,
                    "detection_year": int(year),
                    "geometry_wkt":   geom.wkt,
                    "centroid_lat":   geom.centroid.y,
                    "centroid_lon":   geom.centroid.x,
                    "area_sqm":       area,
                    "area_ha":        area / 10_000,
                    "mean_elevation": wavg("mean_elevation"),
                    "mean_ndwi":      wavg("mean_ndwi"),
                    "mean_ndsi":      wavg("mean_ndsi"),
                    "volume_m3":      vol,
                    "volume_mcm":     vol / 1e6,
                    "season_start":   str(yr["season_start"].iloc[0]),
                    "season_end":     str(yr["season_end"].iloc[0]),
                    "detected_at":    str(yr["detected_at"].max()),
                    "polygon_count":  len(yr),
                })

    cols = ["lake_id", "tile", "detection_year", "geometry_wkt", "centroid_lat",
            "centroid_lon", "area_sqm", "area_ha", "mean_elevation", "mean_ndwi",
            "mean_ndsi", "volume_m3", "volume_mcm", "season_start", "season_end",
            "detected_at", "polygon_count"]
    return pd.DataFrame(out, columns=cols)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def _s3():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def read_raw_from_r2() -> pd.DataFrame:
    s3, bucket = _s3(), os.getenv("R2_BUCKET_NAME", "himalwatch-data")
    frames = []
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix="raw/lakes/"
    ):
        for obj in page.get("Contents", []):
            m = re.fullmatch(r"raw/lakes/([a-z_]+)/(\d{4})/lakes\.parquet", obj["Key"])
            if not m or m.group(1).endswith("_sar"):
                continue
            buf = io.BytesIO()
            s3.download_fileobj(bucket, obj["Key"], buf)
            buf.seek(0)
            df = pd.read_parquet(buf)
            # Trust the path over file contents for tile/year
            df["tile"], df["detection_year"] = m.group(1), int(m.group(2))
            frames.append(df)
            print(f"  read {obj['Key']} ({len(df)} polygons)")
    if not frames:
        raise SystemExit("No raw detections found in R2.")
    return pd.concat(frames, ignore_index=True)


def read_raw_from_dir(d: Path) -> pd.DataFrame:
    frames = []
    for f in sorted(d.glob("*_[0-9][0-9][0-9][0-9].parquet")):
        tile, year = f.stem.rsplit("_", 1)
        df = pd.read_parquet(f)
        df["tile"], df["detection_year"] = tile, int(year)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-dir", type=Path, help="Read {tile}_{year}.parquet from here instead of R2")
    ap.add_argument("--out", type=Path, help="Write locally instead of uploading to R2")
    args = ap.parse_args()

    raw = read_raw_from_dir(args.local_dir) if args.local_dir else read_raw_from_r2()
    linked = link_detections(raw)
    n_lakes = linked["lake_id"].nunique()
    multi = (linked.groupby("lake_id").size() >= 2).sum()
    print(f"Linked {len(raw)} polygons -> {n_lakes} lakes "
          f"({multi} seen in 2+ years), {len(linked)} lake-year rows")

    if args.out:
        linked.to_parquet(args.out, index=False)
        print(f"Written -> {args.out}")
    else:
        buf = io.BytesIO()
        linked.to_parquet(buf, index=False)
        buf.seek(0)
        _s3().upload_fileobj(buf, os.getenv("R2_BUCKET_NAME", "himalwatch-data"), LINKED_KEY)
        print(f"Uploaded -> {LINKED_KEY}")


if __name__ == "__main__":
    main()
