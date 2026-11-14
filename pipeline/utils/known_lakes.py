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


def name_for(lat: float, lon: float, max_km: float = 1.5):
    """Name of the known lake within max_km of this point, else None."""
    best, best_d = None, max_km
    for name, (la, lo, _) in KNOWN_LAKES.items():
        d = math.hypot((lat - la) * 111.0, (lon - lo) * 111.0 * math.cos(math.radians(la)))
        if d < best_d:
            best, best_d = name, d
    return best
