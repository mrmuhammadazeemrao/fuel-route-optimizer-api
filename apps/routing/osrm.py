"""Client for an OSRM-compatible routing server. One HTTP call per route."""

import logging
from dataclasses import dataclass

import polyline
import requests
from django.conf import settings

from apps.routing.exceptions import NoRouteFound, RoutingUnavailable
from apps.routing.locations import Location

logger = logging.getLogger(__name__)

METERS_PER_MILE = 1609.344
POLYLINE_PRECISION = 6

_session = requests.Session()  # reuses the TLS connection across requests


@dataclass(frozen=True)
class Route:
    distance_miles: float
    duration_hours: float
    polyline: str  # encoded with POLYLINE_PRECISION
    coordinates: list[tuple[float, float]]  # (lat, lon) along the route


def fetch_route(start: Location, finish: Location) -> Route:
    url = (
        f"{settings.ROUTING_BASE_URL}/route/v1/driving/"
        f"{start.longitude},{start.latitude};{finish.longitude},{finish.latitude}"
    )
    params = {"overview": "full", "geometries": f"polyline{POLYLINE_PRECISION}"}
    try:
        response = _session.get(url, params=params, timeout=settings.ROUTING_TIMEOUT_SECONDS)
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("OSRM request failed: %s", exc)
        raise RoutingUnavailable from exc

    code = data.get("code")
    if code in {"NoRoute", "NoSegment"}:
        raise NoRouteFound
    if code != "Ok" or not data.get("routes"):
        logger.warning("OSRM error %s (HTTP %s): %s", code, response.status_code, data)
        raise RoutingUnavailable

    route = data["routes"][0]
    return Route(
        distance_miles=route["distance"] / METERS_PER_MILE,
        duration_hours=route["duration"] / 3600,
        polyline=route["geometry"],
        coordinates=polyline.decode(route["geometry"], POLYLINE_PRECISION),
    )
