"""
HimalWatch — Downstream Exposure Analysis

For every detected lake, estimates what is at risk in a GLOF runout scenario:
  - Runout distance (Huggel et al. 2002 empirical formula)
  - Settlements and population within the runout zone (OpenStreetMap)
  - Roads and infrastructure (OSM)

Results are added as columns to the lake GeoDataFrame and included in
mart_lake_inventory so the dashboard can show risk context.

References:
  Huggel et al. (2002): L = 1.9 * V^0.43  (L in m, V in m³)
  Published in: Natural Hazards 25(3), 145-160
  https://doi.org/10.1023/A:1021140230553

OSM data via Overpass API (free, no key required):
  https://overpass-api.de/api/interpreter
"""

import time
from typing import Optional

import overpy
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, box

from utils.volume_estimate import estimate_volume_m3


# ---------------------------------------------------------------------------
# Runout distance
# ---------------------------------------------------------------------------

def estimate_runout_m(volume_m3: float) -> float:
    """
    Huggel et al. (2002) empirical runout distance formula.

    L = 1.9 * V^0.43

    Args:
        volume_m3: Lake volume in cubic metres
    Returns:
        Estimated maximum runout distance in metres

    Uncertainty: ±factor of 2-3 for individual events.
    Use as a screening tool, not a precise hazard boundary.
    """
    if volume_m3 <= 0:
        return 0.0
    return 1.9 * (volume_m3 ** 0.43)


def estimate_runout_km(volume_m3: float) -> float:
    return estimate_runout_m(volume_m3) / 1000


# ---------------------------------------------------------------------------
# OSM queries via Overpass
# ---------------------------------------------------------------------------

_api = overpy.Overpass()


def _overpass_query(query: str, retries: int = 3) -> overpy.Result:
    """Execute Overpass query with retry on rate limit."""
    for attempt in range(retries):
        try:
            return _api.query(query)
        except overpy.exception.OverPyException as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def query_osm_settlements(
    lat: float, lon: float, radius_km: float
) -> gpd.GeoDataFrame:
    """
    Query OSM for populated places within radius_km of (lat, lon).

    Returns GeoDataFrame with: name, place_type, geometry (Point).
    Empty GeoDataFrame if none found.
    """
    r_m = int(radius_km * 1000)
    query = f"""
    [out:json][timeout:30];
    (
      node["place"~"city|town|village|hamlet"](around:{r_m},{lat},{lon});
    );
    out body;
    """
    try:
        result = _overpass_query(query)
    except Exception:
        return gpd.GeoDataFrame(columns=["name", "place_type", "geometry"])

    rows = []
    for node in result.nodes:
        rows.append({
            "name":       node.tags.get("name", "Unknown"),
            "place_type": node.tags.get("place", "unknown"),
            "population": node.tags.get("population", None),
            "geometry":   Point(node.lon, node.lat),
        })

    if not rows:
        return gpd.GeoDataFrame(columns=["name", "place_type", "population", "geometry"])

    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def query_osm_infrastructure(
    lat: float, lon: float, radius_km: float
) -> dict:
    """
    Query OSM for key infrastructure within radius_km of (lat, lon).

    Returns dict with counts: roads_km, hydropower_count, bridges_count.
    """
    r_m = int(radius_km * 1000)
    query = f"""
    [out:json][timeout:30];
    (
      way["highway"](around:{r_m},{lat},{lon});
      node["power"="plant"]["plant:source"="hydro"](around:{r_m},{lat},{lon});
      node["man_made"="bridge"](around:{r_m},{lat},{lon});
    );
    out count;
    """
    try:
        result = _overpass_query(query)
        return {
            "roads_count":      len(result.ways),
            "hydropower_count": sum(
                1 for n in result.nodes
                if n.tags.get("power") == "plant"
            ),
            "bridges_count":    sum(
                1 for n in result.nodes
                if n.tags.get("man_made") == "bridge"
            ),
        }
    except Exception:
        return {"roads_count": 0, "hydropower_count": 0, "bridges_count": 0}


# ---------------------------------------------------------------------------
# Per-lake exposure summary
# ---------------------------------------------------------------------------

def lake_exposure(row: pd.Series) -> dict:
    """
    Compute downstream exposure for a single lake row.

    Args:
        row: Series with centroid_lat, centroid_lon, volume_m3
    Returns:
        dict with runout_km, settlements_in_runout, population_estimate,
        hydropower_in_runout, roads_in_runout, exposure_score
    """
    lat = row["centroid_lat"]
    lon = row["centroid_lon"]
    vol = row.get("volume_m3", estimate_volume_m3(row.get("area_sqm", 0)))

    runout_km = estimate_runout_km(vol)

    # OSM queries
    settlements = query_osm_settlements(lat, lon, runout_km)
    infra       = query_osm_infrastructure(lat, lon, runout_km)

    # Population estimate: use OSM tag where available, else tier estimate
    pop_estimates = []
    if not settlements.empty and "population" in settlements.columns:
        for _, s in settlements.iterrows():
            if s["population"] and str(s["population"]).isdigit():
                pop_estimates.append(int(s["population"]))
            else:
                # Rough estimates by place type
                tier = {"city": 50000, "town": 5000, "village": 500, "hamlet": 50}
                pop_estimates.append(tier.get(s.get("place_type", "hamlet"), 100))

    population_estimate = sum(pop_estimates)

    # Exposure score: 0-10 composite
    score = min(10, (
        min(3, len(settlements)) * 2 +
        min(2, infra["hydropower_count"]) * 2 +
        min(2, infra["roads_count"] / 5) +
        min(1, runout_km / 20)
    ))

    return {
        "runout_km":            round(runout_km, 2),
        "settlements_in_runout": len(settlements),
        "population_estimate":  population_estimate,
        "hydropower_in_runout": infra["hydropower_count"],
        "roads_in_runout":      infra["roads_count"],
        "exposure_score":       round(score, 1),
    }


def add_exposure_to_gdf(
    gdf: gpd.GeoDataFrame,
    max_lakes: Optional[int] = None,
    delay_s: float = 1.0,
) -> gpd.GeoDataFrame:
    """
    Add downstream exposure columns to a lake GeoDataFrame.

    Queries OSM for each lake. Adds delay between requests to respect
    Overpass rate limits (1 req/s is polite for a free public API).

    Args:
        gdf:       Lake GeoDataFrame with centroid_lat, centroid_lon, volume_m3
        max_lakes: Limit for testing (None = all)
        delay_s:   Seconds to wait between OSM queries
    Returns:
        GeoDataFrame with exposure columns added
    """
    subset = gdf if max_lakes is None else gdf.head(max_lakes)
    results = []

    for i, (_, row) in enumerate(subset.iterrows()):
        if i > 0:
            time.sleep(delay_s)
        exp = lake_exposure(row)
        results.append(exp)
        if (i + 1) % 10 == 0:
            print(f"  Exposure: {i + 1}/{len(subset)} lakes processed")

    exp_df = pd.DataFrame(results, index=subset.index)
    return gdf.join(exp_df)
