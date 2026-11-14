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
    # West of 83.8°E the high Himalaya sits north of 29.5°N (Api and Saipal are
    # near 30°N), so these two tiles reach further north. With the old 29.5°N
    # limit far_west contained no glacial lakes at all.
    "far_west":   (80.0, 28.5, 82.1, 30.5),   # Api, Saipal Himal, Humla
    "karnali":    (82.1, 27.5, 83.8, 30.0),   # Kanjiroba, Dolpo, Mugu
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
