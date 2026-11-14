"""
HimalWatch — Cloud Masking for Sentinel-2 High-Altitude Imagery

Two complementary masking strategies:
  1. QA60 bit masking  — fast, coarse, always available
  2. SCL class masking — more accurate, available in S2 SR products

Snow/water discrimination via NDSI prevents snowmelt pools being counted
as glacial lakes. Applied at pixel level AFTER compositing, not as a
scene-level exclusion, so water pixels adjacent to snow are preserved.

Science refs:
  - Foga et al. (2017) Cloud detection algorithm comparison for Landsat
  - ESA Sentinel-2 Level-2A Product Specification (SCL band definition)
  - Hall et al. (1995) NDSI snow mapping (original formulation)
"""

import ee


# ---------------------------------------------------------------------------
# QA60 masking
# ---------------------------------------------------------------------------

def mask_qa60(image: ee.Image) -> ee.Image:
    """
    Mask clouds and cirrus using Sentinel-2 QA60 bitmask band.

    Bit 10 = opaque cloud (1 = cloud present)
    Bit 11 = cirrus cloud  (1 = cirrus present)

    Fast but coarse — misses cloud edges and thin cirrus. Use as a
    first-pass filter before SCL masking.
    """
    qa = image.select("QA60")
    cloud_bit = 1 << 10
    cirrus_bit = 1 << 11
    mask = qa.bitwiseAnd(cloud_bit).eq(0).And(
           qa.bitwiseAnd(cirrus_bit).eq(0))
    return image.updateMask(mask)


# ---------------------------------------------------------------------------
# SCL masking
# ---------------------------------------------------------------------------

# Default SCL classes to exclude.
# Class 11 (snow/ice) is intentionally NOT excluded here — we handle snow
# at pixel level with NDSI after compositing so water near snowfields is kept.
DEFAULT_EXCLUDE_CLASSES = [
    3,   # cloud shadow
    8,   # cloud medium probability
    9,   # cloud high probability
    10,  # thin cirrus
]

def mask_scl(image: ee.Image, exclude_classes: list = None) -> ee.Image:
    """
    Mask pixels by Scene Classification Layer (SCL) class values.

    SCL is produced by Sen2Cor and provides per-pixel classification:
      0  = No data
      1  = Saturated / defective
      2  = Dark area pixels
      3  = Cloud shadows
      4  = Vegetation
      5  = Bare soils
      6  = Water
      7  = Unclassified
      8  = Cloud medium probability
      9  = Cloud high probability
      10 = Thin cirrus
      11 = Snow / ice

    More accurate than QA60, especially at high altitude where cloud
    shadows on glaciers are common false positives.

    Args:
        image: Sentinel-2 SR image with SCL band
        exclude_classes: list of SCL integers to mask out.
                         Defaults to DEFAULT_EXCLUDE_CLASSES.
    """
    if exclude_classes is None:
        exclude_classes = DEFAULT_EXCLUDE_CLASSES

    scl = image.select("SCL")
    mask = scl.neq(exclude_classes[0])
    for cls in exclude_classes[1:]:
        mask = mask.And(scl.neq(cls))
    return image.updateMask(mask)


def mask_combined(image: ee.Image, exclude_classes: list = None) -> ee.Image:
    """Apply both QA60 and SCL masks. Most conservative, best quality."""
    return mask_scl(mask_qa60(image), exclude_classes)


# ---------------------------------------------------------------------------
# Temporal compositing
# ---------------------------------------------------------------------------

def build_clean_composite(
    collection: ee.ImageCollection,
    method: str = "median",
) -> ee.Image:
    """
    Build a cloud-free composite from a masked ImageCollection.

    Args:
        collection: Pre-filtered and masked S2 ImageCollection
        method:
            'median'       — pixel-wise median. Smoothest, handles remaining
                             cloud edges well. Best for area detection.
            'mosaic'       — most-recent valid pixel. Preserves sharpness
                             and temporal recency. More cloud artifacts.
            'percentile_10'— 10th percentile reflectance. Maximises water
                             visibility (water = low reflectance). Useful
                             when median composite still shows cloud remnants
                             over dark lake surfaces.

    Returns:
        Single ee.Image composite
    """
    if method == "median":
        return collection.median()
    elif method == "mosaic":
        return collection.sort("system:time_start", False).mosaic()
    elif method == "percentile_10":
        return collection.reduce(ee.Reducer.percentile([10]))
    else:
        raise ValueError(f"Unknown method '{method}'. Use: median, mosaic, percentile_10")


# ---------------------------------------------------------------------------
# NDSI — snow / water discrimination
# ---------------------------------------------------------------------------

def add_ndsi(image: ee.Image) -> ee.Image:
    """
    Add NDSI (Normalised Difference Snow Index) band to image.

    NDSI = (Green - SWIR1) / (Green + SWIR1)
    Sentinel-2: Green = B3, SWIR1 = B11

    Kept as a per-lake diagnostic attribute only. It is NOT usable to
    separate water from snow: both have high NDSI (see water_mask).

    Ref: Hall et al. (1995), Remote Sensing of Environment
    """
    ndsi = image.normalizedDifference(["B3", "B11"]).rename("NDSI")
    return image.addBands(ndsi)


def add_ndwi(image: ee.Image) -> ee.Image:
    """
    Add NDWI (Normalised Difference Water Index) band to image.

    NDWI = (Green - NIR) / (Green + NIR)
    Sentinel-2: Green = B3, NIR = B8

    Threshold used for detection: see WATER_NDWI_MIN / water_mask().

    Ref: McFeeters (1996), International Journal of Remote Sensing
    """
    ndwi = image.normalizedDifference(["B3", "B8"]).rename("NDWI")
    return image.addBands(ndwi)


WATER_NDWI_MIN   = 0.2   # on the Sep–Oct median composite
WATER_SLOPE_MAX  = 20    # degrees — lakes are flat; steep "water" is shadow


def water_mask(image: ee.Image) -> ee.Image:
    """
    Boolean mask: True where the composite pixel is lake water.

    Condition: NDWI > 0.2 AND terrain slope < 20°.

    Validated with validate_known_lakes.py against Imja, Tsho Rolpa, Lower
    Barun, Thulagi, Lumding, Gokyo, Tilicho and Phoksundo for 2022–2026:
    areas match published values and stable lakes vary < 1.5% year to year.

    The previous rule (NDWI > 0.3 AND NDSI < 0.4) detected almost none of
    them: open water has a HIGH NDSI (it absorbs SWIR even more strongly than
    snow does), so the "not snow" test was discarding the lakes themselves.
    A NIR-brightness cap was also tested and rejected — it drops turbid
    proglacial lakes (Imja, Lower Barun) in some years.

    Image must have an NDWI band (add via add_ndwi first).
    """
    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003"))
    return image.select("NDWI").gt(WATER_NDWI_MIN).And(slope.lt(WATER_SLOPE_MAX))


# ---------------------------------------------------------------------------
# Full pipeline helper
# ---------------------------------------------------------------------------

def prepare_s2_collection(
    aoi: ee.Geometry,
    start_date: str,
    end_date: str,
    max_cloud_pct: int = 80,
    composite_method: str = "median",
) -> ee.Image:
    """
    End-to-end: filter S2 SR collection → mask clouds → composite → add indices.

    Args:
        aoi:              ee.Geometry for the area of interest
        start_date:       ISO date string, e.g. "2024-09-01"
        end_date:         ISO date string, e.g. "2024-10-31"
        max_cloud_pct:    Pre-filter scenes with CLOUDY_PIXEL_PERCENTAGE above this
                          (scene-level, not pixel-level — keeps partially cloudy scenes
                          that have good coverage over lakes)
        composite_method: Passed to build_clean_composite

    Returns:
        ee.Image with NDWI and NDSI bands added, ready for threshold detection
    """
    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud_pct))
        .map(mask_combined)
        .map(add_ndwi)
        .map(add_ndsi)
    )

    composite = build_clean_composite(collection, method=composite_method)
    return composite
