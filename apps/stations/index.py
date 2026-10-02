"""In-memory index of geocoded stations for fast matching against a route.

Loaded from the database once per process (about 6.6k rows); restart the server after
re-running `load_stations` to pick up new prices.
"""

from dataclasses import dataclass
from functools import cache

import numpy as np
from scipy.spatial import cKDTree

from apps.stations.geocoding.geo import EARTH_RADIUS_MILES
from apps.stations.models import FuelStation

# Route points are interpolated to at most this spacing so a station beside a long straight
# segment is measured against the road, not against the segment's distant end points.
ROUTE_STEP_MILES = 0.5


@dataclass(frozen=True)
class StationOnRoute:
    station: FuelStation
    price: float  # USD per gallon
    mile: float  # distance from the start along the route
    off_route_miles: float


@dataclass(frozen=True)
class _StationArrays:
    stations: list[FuelStation]
    lat: np.ndarray
    lon: np.ndarray
    xyz: np.ndarray
    price: np.ndarray


@cache
def _station_arrays() -> _StationArrays:
    stations = list(FuelStation.objects.filter(latitude__isnull=False).order_by("opis_id"))
    lat = np.array([s.latitude for s in stations])
    lon = np.array([s.longitude for s in stations])
    price = np.array([float(s.retail_price) for s in stations])
    return _StationArrays(stations, lat, lon, _to_xyz(lat, lon), price)


def stations_along_route(
    coordinates: list[tuple[float, float]], max_off_route_miles: float
) -> list[StationOnRoute]:
    """Stations within `max_off_route_miles` of the route, sorted by distance along it."""
    data = _station_arrays()
    if not data.stations or len(coordinates) < 2:
        return []

    route = np.asarray(coordinates, dtype=float)
    lat, lon, miles = _densify(route[:, 0], route[:, 1], ROUTE_STEP_MILES)

    # Cheap bounding-box prefilter (1 degree of latitude is about 69 miles).
    pad = max_off_route_miles / 69 + 0.05
    lon_pad = pad / max(np.cos(np.radians(np.abs(lat).max())), 0.1)
    nearby = np.flatnonzero(
        (data.lat >= lat.min() - pad)
        & (data.lat <= lat.max() + pad)
        & (data.lon >= lon.min() - lon_pad)
        & (data.lon <= lon.max() + lon_pad)
    )
    if not nearby.size:
        return []

    chord_limit = 2 * np.sin(max_off_route_miles / (2 * EARTH_RADIUS_MILES))
    chord, nearest = cKDTree(_to_xyz(lat, lon)).query(
        data.xyz[nearby], distance_upper_bound=chord_limit
    )
    hit = np.isfinite(chord)
    off_route = 2 * EARTH_RADIUS_MILES * np.arcsin(chord[hit] / 2)

    matches = [
        StationOnRoute(
            station=data.stations[i],
            price=float(data.price[i]),
            mile=float(miles[point]),
            off_route_miles=float(off),
        )
        for i, point, off in zip(nearby[hit], nearest[hit], off_route, strict=True)
    ]
    return sorted(matches, key=lambda m: (m.mile, m.price))


def _densify(lat: np.ndarray, lon: np.ndarray, step: float):
    """Interpolate points so consecutive ones are at most `step` miles apart.

    Returns (lat, lon, cumulative miles along the route).
    """
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    seg = _haversine_miles(lat[:-1], lon[:-1], lat[1:], lon[1:])
    pieces = np.maximum(1, np.ceil(seg / step).astype(int))
    seg_index = np.repeat(np.arange(seg.size), pieces)
    frac = (np.arange(pieces.sum()) - np.repeat(np.cumsum(pieces) - pieces, pieces)) / np.repeat(
        pieces, pieces
    )
    start_miles = np.concatenate(([0.0], np.cumsum(seg)))

    out_lat = np.append(lat[seg_index] + (lat[seg_index + 1] - lat[seg_index]) * frac, lat[-1])
    out_lon = np.append(lon[seg_index] + (lon[seg_index + 1] - lon[seg_index]) * frac, lon[-1])
    out_miles = np.append(start_miles[seg_index] + seg[seg_index] * frac, start_miles[-1])
    return out_lat, out_lon, out_miles


def _haversine_miles(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def _to_xyz(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Unit-sphere coordinates: Euclidean (chord) distance is monotonic in great-circle distance."""
    lat, lon = np.radians(lat), np.radians(lon)
    return np.column_stack((np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)))
