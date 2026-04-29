"""
HimalWatch — AOI Tile Definitions

The full Nepal Himalaya AOI (lon 80.0–88.2, lat 27.5–29.5) is too large
for a single GEE export job. Split into tiles that each run as independent
GitHub Actions matrix jobs.

Tiles follow major watershed/sub-range boundaries so lake populations are
geographically coherent within each tile.
"""

# Full Nepal Himalaya bounding box
NEPAL_HIMALAYA_BBOX = (80.0, 27.5, 88.2, 29.5)

# Tiles: name → (min_lon, min_lat, max_lon, max_lat)
# Each tile is ~2° wide — tested to complete within GEE timeout limits
TILES = {
    "far_west":   (80.0, 27.5, 82.1, 29.5),   # Api, Saipal Himal
    "karnali":    (82.1, 27.5, 83.8, 29.5),   # Kanjiroba, Dolpo
    "annapurna":  (83.8, 27.5, 85.1, 29.5),   # Annapurna, Manaslu
    "langtang":   (85.1, 27.5, 86.2, 29.5),   # Langtang, Jugal
    "khumbu":     (86.2, 27.5, 87.2, 29.5),   # Everest, Khumbu
    "kangchenjunga": (87.2, 27.5, 88.2, 29.5), # Kangchenjunga, Taplejung
}

ALL_TILE_NAMES = list(TILES.keys())


def get_tile_bbox(tile_name: str) -> tuple:
    """Return (min_lon, min_lat, max_lon, max_lat) for a named tile."""
    if tile_name not in TILES:
        raise ValueError(f"Unknown tile '{tile_name}'. Valid: {ALL_TILE_NAMES}")
    return TILES[tile_name]
