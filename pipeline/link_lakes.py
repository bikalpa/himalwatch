"""
HimalWatch — Link lake detections across years

The detection step assigns a fresh random lake_id on every run (each CI runner
starts with no master registry), so the same physical lake had a different id
every year and no area trend could ever be computed.

This step fixes identity after the fact, from geometry alone:

  1. Read every raw/lakes/{tile}/{year}/lakes.parquet from R2.
  2. Two detections are the same lake if their polygons overlap (any year
     pair), or if they touch in the same year (a lake cut by a processing
     strip/tile seam). Connected components of that graph are lakes. Overlap is used instead of centroid distance because a
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
import json
import io
import os
import re
import sys
from pathlib import Path

import pandas as pd
from shapely import wkt
from shapely.geometry import Point, shape
from shapely.prepared import prep
from shapely.ops import unary_union
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).parent))
from utils.volume_estimate import estimate_volume_m3  # noqa: E402
from utils.lake_names import LakeNames  # noqa: E402

LINKED_KEY = "linked/lake_detections.parquet"
# Ignore sliver contacts: polygons must share at least this fraction of the
# smaller one to count as the same lake.
MIN_OVERLAP_FRAC = 0.10
# Only link detections made with the current method (Sep–Oct composite).
# Older files in R2 used a Jun–Sep window and a broken water test.
SEASON_START_MM = "09-01"
# Pieces of one lake detected in the same year are merged when the gap between
# them is at most about one 20 m pixel (~25 m). Two causes: processing strip /
# tile seams, and the per-pixel slope mask — the 2000-era SRTM terrain still
# shows an ice cliff where a lake has since grown into its glacier, which cut
# a one-pixel line through Thulagi and reported its growing end as a separate
# 18 ha lake.
SEAM_TOLERANCE_DEG = 0.00025
# The processing tiles are rectangles that reach well into Tibet. Lakes are
# still tracked there, but only lakes inside Nepal (plus this margin, ~5 km,
# for lakes sitting on the border divide) can raise alerts.
# Boundary: geoBoundaries NPL ADM0, full resolution simplified to ~30 m
# (CC BY 4.0). The heavily simplified version it replaced was up to several km
# off along the crest, which is exactly where the lakes are.
NEPAL_BOUNDARY = Path(__file__).parent / "utils" / "nepal_boundary.geojson"
NEPAL_MARGIN_DEG = 0.05
# Indian border states (Uttarakhand, Himachal Pradesh, Sikkim) from
# OpenStreetMap. A lake outside Nepal and outside these is in China (Tibet):
# the tiles touch no other country. Where claims overlap (Kalapani /
# Limpiyadhura) the Nepal boundary file wins — this is a display label only.
INDIA_BOUNDARY = Path(__file__).parent / "utils" / "india_boundary.geojson"


def nepal_area():
    """Prepared Nepal polygon, buffered by the border margin."""
    gj = json.loads(NEPAL_BOUNDARY.read_text())
    return prep(shape(gj["features"][0]["geometry"]).buffer(NEPAL_MARGIN_DEG))


def country_lookup():
    """Function (lon, lat) -> 'Nepal' | 'India' | 'China'."""
    def load(path):
        return prep(shape(json.loads(path.read_text())["features"][0]["geometry"]))
    nepal, india = load(NEPAL_BOUNDARY), load(INDIA_BOUNDARY)

    def country(lon, lat):
        p = Point(lon, lat)
        return "Nepal" if nepal.contains(p) else "India" if india.contains(p) else "China"
    return country


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
    nepal = nepal_area()
    names = LakeNames()
    country_of = country_lookup()
    grp = raw.reset_index(drop=True)
    geoms = grp["geom"].tolist()
    years = grp["detection_year"].tolist()
    parent = list(range(len(geoms)))
    tree = STRtree(geoms)

    # 1. Same lake across years: polygons overlap.
    left, right = tree.query(geoms, predicate="intersects")
    for i, j in zip(left, right):
        if i >= j:
            continue
        inter = geoms[i].intersection(geoms[j]).area
        if inter >= MIN_OVERLAP_FRAC * min(geoms[i].area, geoms[j].area):
            parent[_find(parent, i)] = _find(parent, j)

    # 2. Same lake, same year, cut in two by a processing seam (longitude
    #    strips and tile edges): the pieces touch but do not overlap.
    left, right = tree.query([g.buffer(SEAM_TOLERANCE_DEG) for g in geoms],
                             predicate="intersects")
    for i, j in zip(left, right):
        if i < j and years[i] == years[j]:
            parent[_find(parent, i)] = _find(parent, j)

    grp["component"] = [_find(parent, i) for i in range(len(geoms))]

    for _, comp in grp.groupby("component"):
        first_year = comp["detection_year"].min()
        anchor = unary_union(
            comp.loc[comp["detection_year"] == first_year, "geom"].tolist()
        ).centroid
        lake_id = hashlib.sha1(f"{anchor.y:.4f},{anchor.x:.4f}".encode()).hexdigest()[:8]
        # A lake straddling a tile edge belongs to the tile holding most of it
        tile = comp.groupby("tile")["area_sqm"].sum().idxmax()
        in_nepal = any(nepal.intersects(g) for g in comp["geom"])
        # Name from the newest outline; unnamed lakes get a "near X" hint instead.
        last_year = comp["detection_year"].max()
        newest = unary_union(comp.loc[comp["detection_year"] == last_year, "geom"].tolist())
        country = country_of(newest.centroid.x, newest.centroid.y)
        name = names.name_for(newest)
        name_hint = None if name else names.hint_for(newest.centroid.y, newest.centroid.x)

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
                "in_nepal":       in_nepal,
                "country":        country,
                "name":           name,
                "name_hint":      name_hint,
            })

    cols = ["lake_id", "tile", "detection_year", "geometry_wkt", "centroid_lat",
            "centroid_lon", "area_sqm", "area_ha", "mean_elevation", "mean_ndwi",
            "mean_ndsi", "volume_m3", "volume_mcm", "season_start", "season_end",
            "detected_at", "polygon_count", "in_nepal", "country", "name", "name_hint"]
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
    n_nepal = linked.loc[linked["in_nepal"], "lake_id"].nunique()
    print(f"Linked {len(raw)} polygons -> {n_lakes} lakes "
          f"({multi} seen in 2+ years, {n_nepal} in Nepal), {len(linked)} lake-year rows")

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
