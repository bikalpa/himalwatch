"""
HimalWatch — Validate water-detection rules against well-known lakes

Measures the detected area of a handful of well-documented Nepal lakes under
several mask rules / seasons / years, without running the full tile pipeline.
Use it before changing detection thresholds.

Good rule = areas close to the published values AND stable year to year for
lakes known to be stable (Tilicho, Phoksundo, Gokyo).

Usage:
    python pipeline/gee/validate_known_lakes.py --years 2022 2024 2026
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).parent))
from cloud_masking import mask_combined  # noqa: E402
from lake_detection import authenticate_gee  # noqa: E402

# name: (lat, lon, published area km2 — approximate, for orientation)
KNOWN = {
    "Imja Tsho":     (27.899, 86.923, 1.5),
    "Tsho Rolpa":    (27.862, 86.477, 1.6),
    "Lower Barun":   (27.798, 87.095, 2.0),
    "Thulagi":       (28.490, 84.485, 0.9),
    "Lumding Tsho":  (27.779, 86.614, 1.2),
    "Gokyo (Dudh)":  (27.953, 86.694, 0.43),
    "Tilicho":       (28.688, 83.854, 4.8),
    "Phoksundo":     (29.210, 82.958, 4.9),
}
SEARCH_RADIUS_M = 1500

SEASONS = {
    "Sep01-Oct31": ("09-01", "10-31"),
    "Sep01-Nov15": ("09-01", "11-15"),
}

# Glacier-heavy box (Khumbu/Ngozumpa) used to compare over-detection between
# rules: reports "polygons>=1ha / total km2" in the last column.
FP_BOX = [86.60, 27.90, 86.95, 28.05]


def _collection(aoi, year, season):
    s, e = SEASONS[season]
    return (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(f"{year}-{s}", f"{year}-{e}")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
        .map(mask_combined)
    )


def _slope():
    return ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003"))


def _img_water(img, ndwi_t, nir_max=None):
    """Water test for one image/composite: NDWI above threshold, optional NIR cap."""
    w = img.normalizedDifference(["B3", "B8"]).gt(ndwi_t)
    if nir_max:
        w = w.And(img.select("B8").lt(nir_max))
    return w


# rule name -> (kind, ndwi threshold, NIR cap or None)
RULE_SPECS = {
    "med_ndwi0.2":          ("med", 0.20, None),
    "med_ndwi0.2_nir2500":  ("med", 0.20, 2500),
    "med_ndwi0.15_nir2500": ("med", 0.15, 2500),
    "freq30_ndwi0.15_nir2500": ("freq", 0.15, 2500),
}
RULES = list(RULE_SPECS)


def mask_for(rule, aoi, year, season):
    kind, t, nir = RULE_SPECS[rule]
    col = _collection(aoi, year, season)
    flat = _slope().lt(20)
    if kind == "med":
        return _img_water(col.median(), t, nir).And(flat)
    freq = col.map(lambda i: _img_water(i, t, nir).rename("w")).mean()
    return freq.gte(0.3).And(flat)


def measure(rule, year, season):
    def one(name):
        lat, lon, _ = KNOWN[name]
        pt = ee.Geometry.Point([lon, lat])
        aoi = pt.buffer(4000)
        m = mask_for(rule, aoi, year, season).selfMask()
        vec = m.reduceToVectors(geometry=aoi, scale=10, maxPixels=1e9,
                                geometryType="polygon", eightConnected=True)
        near = vec.filterBounds(pt.buffer(SEARCH_RADIUS_M))
        near = near.map(lambda f: f.set("a", f.geometry().area(1)))
        # largest water body touching the search circle
        return ee.Number(ee.Algorithms.If(near.size().gt(0), near.aggregate_max("a"), 0))
    def fp_box():
        box = ee.Geometry.Rectangle(FP_BOX)
        m = mask_for(rule, box, year, season).And(
            ee.Image("USGS/SRTMGL1_003").gt(3500)).selfMask()
        vec = m.reduceToVectors(geometry=box, scale=20, maxPixels=1e9,
                                geometryType="polygon", eightConnected=True)
        vec = vec.map(lambda f: f.set("a", f.geometry().area(1))).filter(ee.Filter.gte("a", 1e4))
        return ee.List([vec.size(), vec.aggregate_sum("a")])

    names = list(KNOWN)
    try:
        vals, box = ee.List([ee.List([one(n) for n in names]), fp_box()]).getInfo()
        vals = vals + [f"{box[0]}/{box[1] / 1e6:.1f}km2"]
    except Exception as exc:  # noqa: BLE001
        return rule, year, season, {n: f"ERR {str(exc)[:40]}" for n in names + ["box"]}
    return rule, year, season, dict(zip(names + ["box"], vals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=[2022, 2023, 2024, 2025, 2026])
    args = ap.parse_args()
    authenticate_gee(os.getenv("GEE_PROJECT", "himalwatch"))

    jobs = [(r, y, s) for s in SEASONS for r in RULES for y in args.years]
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda j: measure(*j), jobs))

    names = list(KNOWN) + ["box"]
    KNOWN["box"] = (0, 0, 0)
    print("Detected area in km2 (largest water body near each lake)\n")
    print(f"{'season':15} {'rule':26} {'year':4} " + " ".join(f"{n[:11]:>11}" for n in names))
    print(f"{'published ~':46} " + " ".join(f"{KNOWN[n][2]:>11.2f}" for n in names))
    for rule, year, season, vals in results:
        cells = " ".join(
            f"{v / 1e6:>11.2f}" if isinstance(v, (int, float)) else f"{v[:11]:>11}"
            for v in (vals[n] for n in names)
        )
        print(f"{season:15} {rule:26} {year:4} {cells}")


if __name__ == "__main__":
    main()
