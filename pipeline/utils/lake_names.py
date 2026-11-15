"""
Real lake names from OpenStreetMap.

lake_names.json holds every named natural=water body in the Nepal Himalaya
bounding box (rivers and reservoirs excluded): {"name", "bbox": [minlon,
minlat, maxlon, maxlat]}. Latin-script names are preferred (name:en, then
name). Data (c) OpenStreetMap contributors, ODbL.

Refresh by re-querying Overpass for named natural=water in the bbox; names change
rarely, so the file is committed rather than fetched on every run.
"""
import json
import math
from pathlib import Path

from shapely.geometry import box
from shapely.strtree import STRtree

_FILE = Path(__file__).parent / "lake_names.json"
MIN_BBOX_OVERLAP = 0.5      # share of the smaller bounding box that must overlap
HINT_MAX_KM = 10.0          # "x km NE of <named lake>" only within this range
_COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _latin(s: str) -> bool:
    return all(ord(c) < 0x250 for c in s)


class LakeNames:
    def __init__(self, path: Path = _FILE):
        self.items = json.loads(path.read_text())
        self.boxes = [box(*i["bbox"]) for i in self.items]
        self.tree = STRtree(self.boxes)
        self.latin = [(i["name"], b.centroid.y, b.centroid.x)
                      for i, b in zip(self.items, self.boxes) if _latin(i["name"])]

    def name_for(self, geom):
        """OSM name of the water body this polygon is, or None."""
        gb = box(*geom.bounds)
        best, best_s = None, MIN_BBOX_OVERLAP
        for i in self.tree.query(geom, predicate="intersects"):
            b = self.boxes[i]
            s = gb.intersection(b).area / max(min(gb.area, b.area), 1e-12)
            if s >= best_s:
                best, best_s = self.items[i]["name"], s
        return best

    def hint_for(self, lat: float, lon: float):
        """'3.2 km NE of Imja Tsho' for an unnamed lake, or None if nothing is near."""
        best, best_d = None, HINT_MAX_KM
        for name, la, lo in self.latin:
            dy = (lat - la) * 111.0
            dx = (lon - lo) * 111.0 * math.cos(math.radians(la))
            d = math.hypot(dx, dy)
            if d < best_d:
                best, best_d = (name, dx, dy), d
        if not best:
            return None
        name, dx, dy = best
        bearing = (math.degrees(math.atan2(dx, dy)) + 360) % 360
        return f"{best_d:.1f} km {_COMPASS[int((bearing + 22.5) // 45) % 8]} of {name}"
