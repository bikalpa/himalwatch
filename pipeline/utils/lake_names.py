"""
Real lake names from OpenStreetMap.

lake_names.json holds every named natural=water body in the Nepal Himalaya
bounding box (rivers and reservoirs excluded): {"name", "bbox": [minlon,
minlat, maxlon, maxlat]}. Latin-script names are preferred (name:en, then
name). Data (c) OpenStreetMap contributors, ODbL.

lake_points.json adds lakes Wikidata knows by name (a point each, CC0), used
when OpenStreetMap has no name for the outline. places.json holds named peaks,
passes, glaciers and settlements near the lakes (OpenStreetMap), so a lake
nobody has named can still say what it sits next to.

Refresh by re-querying Overpass for named natural=water in the bbox; names change
rarely, so the file is committed rather than fetched on every run.
"""
import json
import math
from pathlib import Path

from shapely.geometry import Point, box
from shapely.strtree import STRtree

_FILE = Path(__file__).parent / "lake_names.json"
_POINTS = Path(__file__).parent / "lake_points.json"
_PLACES = Path(__file__).parent / "places.json"
POINT_TOLERANCE_DEG = 0.001  # a Wikidata point may sit ~100 m off the shore
GLACIER_AT_KM = 0.3          # closer than this to a glacier's extent: "at X Glacier"
MIN_BBOX_OVERLAP = 0.5      # share of the smaller bounding box that must overlap
HINT_MAX_KM = 10.0          # "x km NE of <named lake>" only within this range
# Names people in Nepal actually use, where OpenStreetMap's main tag differs.
ALIASES = {"Dona Lake": "Thulagi Lake (Dona Tal)"}
# OpenStreetMap "names" that are only a description of the thing.
GENERIC = {"tarn", "glacial lake", "glacier lake", "glacier", "lake", "pond",
           "ponds", "pool", "pokhari", "taal", "tal", "kunda", "kund", "tso",
           "tsho", "co", "water", "unnamed", "moraine lake", "ice lake"}
_COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _latin(s: str) -> bool:
    return all(ord(c) < 0x250 for c in s)


class LakeNames:
    def __init__(self, path: Path = _FILE):
        self.items = [i for i in json.loads(path.read_text())
                      if i["name"].strip().lower() not in GENERIC]
        for i in self.items:
            i["name"] = ALIASES.get(i["name"], i["name"])
        self.boxes = [box(*i["bbox"]) for i in self.items]
        self.tree = STRtree(self.boxes)
        self.latin = [(i["name"], b.centroid.y, b.centroid.x)
                      for i, b in zip(self.items, self.boxes) if _latin(i["name"])]
        self.points = json.loads(_POINTS.read_text()) if _POINTS.exists() else []
        self.places = json.loads(_PLACES.read_text()) if _PLACES.exists() else []

    def name_for(self, geom):
        """OSM name of the water body this polygon is, or None."""
        gb = box(*geom.bounds)
        best, best_s = None, MIN_BBOX_OVERLAP
        for i in self.tree.query(geom, predicate="intersects"):
            b = self.boxes[i]
            s = gb.intersection(b).area / max(min(gb.area, b.area), 1e-12)
            if s >= best_s:
                best, best_s = self.items[i]["name"], s
        if best:
            return best
        near = geom.buffer(POINT_TOLERANCE_DEG)
        minx, miny, maxx, maxy = near.bounds
        for p in self.points:
            if minx <= p["lon"] <= maxx and miny <= p["lat"] <= maxy \
                    and near.contains(Point(p["lon"], p["lat"])):
                return ALIASES.get(p["name"], p["name"])
        return None

    def hint_for(self, lat: float, lon: float):
        """
        '3.2 km NE of Imja Tsho' for an unnamed lake: the nearest named lake,
        peak, pass, glacier or settlement within range. None if nothing is near.
        """
        kx = 111.0 * math.cos(math.radians(lat))
        best, best_d = None, HINT_MAX_KM
        for name, la, lo in self.latin:
            dx, dy = (lon - lo) * kx, (lat - la) * 111.0
            d = math.hypot(dx, dy)
            if d < best_d:
                best, best_d = (name, dx, dy, False), d
        for p in self.places:
            dx, dy = (lon - p["lon"]) * kx, (lat - p["lat"]) * 111.0
            d, at = math.hypot(dx, dy), False
            if p.get("bbox"):
                # Glaciers are long: measure to their extent, not their middle
                x0, y0, x1, y1 = p["bbox"]
                ex = max(x0 - lon, 0, lon - x1) * kx
                ey = max(y0 - lat, 0, lat - y1) * 111.0
                e = math.hypot(ex, ey)
                if e < GLACIER_AT_KM:
                    d, at = e, True
            if d < best_d:
                best, best_d = (p["name"], dx, dy, at), d
        if not best:
            return None
        name, dx, dy, at = best
        if at:
            return f"at {name}"
        bearing = (math.degrees(math.atan2(dx, dy)) + 360) % 360
        return f"{best_d:.1f} km {_COMPASS[int((bearing + 22.5) // 45) % 8]} of {name}"
