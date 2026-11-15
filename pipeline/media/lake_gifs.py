"""
HimalWatch — Per-lake satellite snapshots and growth GIFs

For each lake of interest, stores one Sentinel-2 true-colour snapshot per
season in R2 and stitches them into an animated GIF with that season's
detected outline, so people can see the scale of growth.

R2 layout:
    media/lakes/{lake_id}/meta.json      frame region (fixed so frames align)
    media/lakes/{lake_id}/{year}.png     raw snapshot, one per season (kept forever)
    media/lakes/{lake_id}/growth.gif     animation rebuilt each run

Snapshots are cached: a run only downloads seasons it does not have yet
(plus the newest season, which is refreshed).

Lakes covered: every lake in mart_change_alerts (growing), then the largest
lakes with >= 3 seasons, up to --max-lakes.

Usage:
    python pipeline/media/lake_gifs.py --max-lakes 60
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
from PIL import Image, ImageDraw, ImageFont
from shapely import wkt

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "gee"))

FIRST_YEAR   = 2019            # Sentinel-2 surface reflectance covers Nepal from 2019
FRAME_PX     = 480
PAD_FRAC     = 0.6             # padding around the lake's all-time extent
MIN_HALF_M   = 700             # never zoom in tighter than this
SEASON       = ("09-01", "10-31")
FRAME_MS, LAST_FRAME_MS = 900, 2500


# ---------------------------------------------------------------------------
# R2 helpers
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


BUCKET = os.getenv("R2_BUCKET_NAME", "himalwatch-data")


def _get(s3, key):
    try:
        return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except Exception:  # noqa: BLE001 — missing key
        return None


def _put(s3, key, body: bytes, ctype: str):
    s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType=ctype,
                  CacheControl="public, max-age=3600")


def _parquet(s3, key) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(_get(s3, key)))


# ---------------------------------------------------------------------------
# Geometry / drawing (pure — no network)
# ---------------------------------------------------------------------------

def frame_region(geoms) -> list:
    """[min_lon, min_lat, max_lon, max_lat] square-ish box around all geometries."""
    minx = min(g.bounds[0] for g in geoms); miny = min(g.bounds[1] for g in geoms)
    maxx = max(g.bounds[2] for g in geoms); maxy = max(g.bounds[3] for g in geoms)
    lat = (miny + maxy) / 2
    m_per_deg_lat, m_per_deg_lon = 111_320.0, 111_320.0 * math.cos(math.radians(lat))
    half = max((maxx - minx) * m_per_deg_lon, (maxy - miny) * m_per_deg_lat) / 2
    half = max(half * (1 + PAD_FRAC), MIN_HALF_M)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    return [cx - half / m_per_deg_lon, cy - half / m_per_deg_lat,
            cx + half / m_per_deg_lon, cy + half / m_per_deg_lat]


def region_contains(region, geoms) -> bool:
    return all(
        region[0] <= g.bounds[0] and region[1] <= g.bounds[1]
        and region[2] >= g.bounds[2] and region[3] >= g.bounds[3]
        for g in geoms
    )


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:          # Pillow < 10.1
        return ImageFont.load_default()


def _text(draw, xy, s, size, fill=(255, 255, 255)):
    draw.text(xy, s, font=_font(size), fill=fill, stroke_width=2, stroke_fill=(0, 0, 0))


def annotate(png: bytes, region, year: int, geom, area_ha, title: str) -> Image.Image:
    """Draw outline + labels onto a raw snapshot."""
    img = Image.open(io.BytesIO(png)).convert("RGB").resize((FRAME_PX, FRAME_PX))
    d = ImageDraw.Draw(img)
    w = h = FRAME_PX

    def px(x, y):
        return ((x - region[0]) / (region[2] - region[0]) * w,
                (region[3] - y) / (region[3] - region[1]) * h)

    if geom is not None:
        polys = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
        for p in polys:
            if p.geom_type != "Polygon":
                continue
            pts = [px(x, y) for x, y in p.exterior.coords]
            d.line(pts + [pts[0]], fill=(0, 229, 255), width=2)

    _text(d, (12, 8), str(year), 34)
    label = f"{area_ha:,.1f} ha" if area_ha is not None else "not detected"
    _text(d, (12, 48), label, 20, fill=(0, 229, 255) if area_ha is not None else (255, 200, 80))
    _text(d, (12, h - 28), title, 15)

    # scale bar: nearest "nice" length around a quarter of the frame
    lat = (region[1] + region[3]) / 2
    frame_m = (region[2] - region[0]) * 111_320.0 * math.cos(math.radians(lat))
    nice = min((100, 200, 500, 1000, 2000, 5000, 10000), key=lambda v: abs(v - frame_m / 4))
    bar = nice / frame_m * w
    d.line([(w - 14 - bar, h - 42), (w - 14, h - 42)], fill=(255, 255, 255), width=3)
    lbl = f"{nice // 1000} km" if nice >= 1000 else f"{nice} m"
    _text(d, (w - 14 - bar, h - 64), lbl, 14)
    return img


def build_gif(frames: list) -> bytes:
    buf = io.BytesIO()
    durations = [FRAME_MS] * (len(frames) - 1) + [LAST_FRAME_MS]
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Earth Engine snapshot
# ---------------------------------------------------------------------------

def fetch_snapshot(region, year: int) -> bytes | None:
    import ee
    from cloud_masking import mask_combined

    aoi = ee.Geometry.Rectangle(region)
    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(f"{year}-{SEASON[0]}", f"{year}-{SEASON[1]}")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
        .map(mask_combined)
    )
    if col.size().getInfo() == 0:
        return None
    vis = col.median().visualize(bands=["B4", "B3", "B2"], min=0, max=3500, gamma=1.25)
    try:
        # computePixels only needs the "compute" permission the pipeline already has.
        return ee.data.computePixels({
            "expression": vis,
            "fileFormat": "PNG",
            "grid": {
                "dimensions": {"width": FRAME_PX, "height": FRAME_PX},
                "affineTransform": {
                    "scaleX": (region[2] - region[0]) / FRAME_PX, "shearX": 0,
                    "translateX": region[0],
                    "shearY": 0, "scaleY": -(region[3] - region[1]) / FRAME_PX,
                    "translateY": region[3],
                },
                "crsCode": "EPSG:4326",
            },
        })
    except Exception as exc:  # noqa: BLE001
        if "429" in str(exc) or "concurrency" in str(exc):
            raise
        # Fallback: thumbnails API (needs the Earth Engine Resource Writer role)
        url = vis.getThumbURL({"region": aoi, "dimensions": f"{FRAME_PX}x{FRAME_PX}",
                               "crs": "EPSG:4326", "format": "png"})
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        return r.content


# ---------------------------------------------------------------------------
# Per-lake job
# ---------------------------------------------------------------------------

def process_lake(s3, lake_id: str, hist: pd.DataFrame, latest_year: int) -> str:
    name = hist["name"].iloc[0] if "name" in hist and isinstance(hist["name"].iloc[0], str) else None
    prefix = f"media/lakes/{lake_id}"
    by_year = {int(r.detection_year): (wkt.loads(r.geometry_wkt), float(r.area_ha))
               for r in hist.itertuples()}
    geoms = [g for g, _ in by_year.values()]

    meta = json.loads(_get(s3, f"{prefix}/meta.json") or "null")
    fresh = not meta or not region_contains(meta["region"], geoms)
    region = frame_region(geoms) if fresh else meta["region"]
    if fresh:
        _put(s3, f"{prefix}/meta.json", json.dumps({"region": region}).encode(), "application/json")

    c = geoms[-1].centroid
    latest_ha = by_year[max(by_year)][1]
    title = f"{name or 'Unnamed lake'} · {c.y:.3f}N {c.x:.3f}E"

    frames = []
    for year in range(FIRST_YEAR, latest_year + 1):
        key = f"{prefix}/{year}.png"
        png = None if (fresh or year == latest_year) else _get(s3, key)
        if png is None:
            png = with_retry(lambda: fetch_snapshot(region, year), f"{lake_id}/{year}")
            if png is None:
                continue
            _put(s3, key, png, "image/png")
        geom, area = by_year.get(year, (None, None))
        frames.append(annotate(png, region, year, geom, area, title))

    if len(frames) < 2:
        return f"{lake_id}: only {len(frames)} usable frame(s), skipped"
    _put(s3, f"{prefix}/growth.gif", build_gif(frames), "image/gif")
    return f"{lake_id}: {len(frames)} frames"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-lakes", type=int, default=60)
    args = ap.parse_args()

    from lake_detection import authenticate_gee
    global with_retry
    from lake_detection import with_retry
    authenticate_gee(os.getenv("GEE_PROJECT", "himalwatch"))

    s3 = _s3()
    linked = _parquet(s3, "linked/lake_detections.parquet")
    inv    = _parquet(s3, "marts/mart_lake_inventory.parquet")
    alerts = _parquet(s3, "marts/mart_change_alerts.parquet")

    wanted = list(alerts["lake_id"])
    big = inv[inv["detection_count"] >= 3].sort_values("latest_area_sqm", ascending=False)
    wanted += [i for i in big["lake_id"] if i not in set(wanted)]
    wanted = wanted[: args.max_lakes]
    latest_year = int(linked["detection_year"].max())
    print(f"Building GIFs for {len(wanted)} lakes ({len(alerts)} growing), "
          f"{FIRST_YEAR}–{latest_year}")

    def run(lake_id):
        try:
            return process_lake(s3, lake_id, linked[linked["lake_id"] == lake_id]
                                .sort_values("detection_year"), latest_year)
        except Exception as exc:  # noqa: BLE001 — one lake must not stop the rest
            return f"{lake_id}: FAILED {exc}"

    with ThreadPoolExecutor(3) as ex:
        for line in ex.map(run, wanted):
            print(" ", line)


if __name__ == "__main__":
    main()
