"""
Well-known lakes used for validation and for naming lakes in alerts.

name: (lat, lon, published area km2 — approximate, for orientation only)
"""
import math

KNOWN_LAKES = {
    "Imja Tsho":     (27.899, 86.923, 1.5),
    "Tsho Rolpa":    (27.862, 86.477, 1.6),
    "Lower Barun":   (27.798, 87.095, 2.0),
    "Thulagi":       (28.490, 84.485, 0.9),
    "Lumding Tsho":  (27.779, 86.614, 1.2),
    "Gokyo (Dudh Pokhari)": (27.953, 86.694, 0.43),
    "Tilicho":       (28.688, 83.854, 4.8),
    "Phoksundo":     (29.210, 82.958, 4.9),
}


def nearest_known(lat: float, lon: float, max_km: float = 1.5):
    """(name, published_km2) of the known lake within max_km of this point, else None."""
    best, best_d = None, max_km
    for name, (la, lo, km2) in KNOWN_LAKES.items():
        d = math.hypot((lat - la) * 111.0, (lon - lo) * 111.0 * math.cos(math.radians(la)))
        if d < best_d:
            best, best_d = (name, km2), d
    return best


def name_for(lat: float, lon: float, area_ha: float = None, fallback: str = "Lake"):
    """
    Human name for a detected lake.

    The known lake's own name is used only when the size also matches (within
    2x of the published area) — small ponds next to a famous lake are labelled
    "<fallback> (near <name>)" so they are not mistaken for it.
    """
    hit = nearest_known(lat, lon)
    if not hit:
        return fallback
    name, km2 = hit
    if area_ha is None or 0.5 <= (area_ha / 100.0) / km2 <= 2.0:
        return name
    return f"{fallback} (near {name})"
