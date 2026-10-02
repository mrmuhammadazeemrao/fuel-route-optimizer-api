import math

import shapely

EARTH_RADIUS_MILES = 3958.8
# The 1:5M state boundaries generalize the shoreline, so points this close to land count as on it.
SHORELINE_TOLERANCE_MILES = 0.5


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def mean_point(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def is_offshore(land: shapely.Geometry, lat: float, lon: float) -> bool:
    """Whether a point lies out in the water rather than on (or just off) `land`."""
    if shapely.contains_xy(land, lon, lat):
        return False
    shore_lon, shore_lat = shapely.shortest_line(land, shapely.Point(lon, lat)).coords[0]
    return haversine_miles(lat, lon, shore_lat, shore_lon) > SHORELINE_TOLERANCE_MILES
