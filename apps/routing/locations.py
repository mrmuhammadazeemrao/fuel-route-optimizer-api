"""Resolve start/finish input ("City, ST" or "lat,lon") to coordinates without any API call.

Only the contiguous US (lower 48 + DC) is supported: the fuel price data covers those states,
and Alaska/Hawaii can't be reached by road without leaving the country.
"""

import csv
import json
import re
from dataclasses import dataclass
from functools import cache

import shapely
from django.conf import settings
from shapely.geometry import shape

from apps.stations.geocoding.places import normalize

SUPPORTED_STATES = frozenset(
    "AL AZ AR CA CO CT DE DC FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
    "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
OTHER_US_STATES = frozenset({"AK", "HI", "PR"})
FORMAT_HELP = "Use 'City, ST' (e.g. 'Chicago, IL') or 'lat,lon' (e.g. '41.8781,-87.6298')."

_COORDINATES_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_ALTERNATE_NAME_RE = re.compile(r"(.+) \((.+)\)")  # "San Buenaventura (Ventura)"
_NAME_PREFIX_RE = re.compile(r"^(?:City|Town|Village) of ")  # "Town of Pecos"
_COMMON_NAMES = {"Boise City": "Boise"}  # Census name -> the name people use


class LocationError(ValueError):
    pass


@dataclass(frozen=True)
class Location:
    name: str
    latitude: float
    longitude: float


def resolve_location(query: str) -> Location:
    if match := _COORDINATES_RE.match(query):
        return _resolve_coordinates(float(match.group(1)), float(match.group(2)))
    if "," in query:
        city, state = (part.strip() for part in query.rsplit(",", 1))
        return _resolve_city(city, state.upper())
    raise LocationError(f"Unrecognized location '{query}'. {FORMAT_HELP}")


def _resolve_coordinates(lat: float, lon: float) -> Location:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise LocationError(f"Invalid coordinates '{lat},{lon}'. {FORMAT_HELP}")
    state = state_at(lat, lon)
    if state is None:
        raise LocationError(
            f"Coordinates {lat},{lon} are outside the contiguous United States "
            "(note the order is latitude,longitude)."
        )
    return Location(f"{lat:.5f},{lon:.5f} ({state})", lat, lon)


def _resolve_city(city: str, state: str) -> Location:
    if state in OTHER_US_STATES:
        raise LocationError(f"{state} is not supported: only the contiguous United States is.")
    if state not in SUPPORTED_STATES:
        raise LocationError(f"Unknown US state code '{state}'. {FORMAT_HELP}")
    place = _places().get((normalize(city), state))
    if place is None:
        raise LocationError(f"City '{city}, {state}' not found.")
    return place


def state_at(lat: float, lon: float) -> str | None:
    for state, geometry in state_boundaries():
        if shapely.contains_xy(geometry, lon, lat):
            return state
    return None


@cache
def _places() -> dict[tuple[str, str], Location]:
    places: dict[tuple[str, str], Location] = {}
    aliases: dict[tuple[str, str], Location] = {}
    with settings.US_PLACES_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            location = Location(
                f"{row['name']}, {row['state']}", float(row["latitude"]), float(row["longitude"])
            )
            places.setdefault((normalize(row["name"]), row["state"]), location)
            for alias in _aliases(row["name"]):
                aliases.setdefault((normalize(alias), row["state"]), location)
    return aliases | places


def _aliases(name: str) -> set[str]:
    """Shorter names a place is also found by: "Nashville-Davidson" -> "Nashville",
    "Louisville/Jefferson County" -> "Louisville", "San Buenaventura (Ventura)" -> "Ventura",
    "Town of Pecos" -> "Pecos", "Boise City" -> "Boise"."""
    match = _ALTERNATE_NAME_RE.fullmatch(name)
    names = set(match.groups()) if match else {name}
    for full in list(names):
        names.add(re.split("[-/]", full, maxsplit=1)[0])
        names.add(_NAME_PREFIX_RE.sub("", full))
    names.add(_COMMON_NAMES.get(name, name))
    return names - {name}


@cache
def state_boundaries() -> list[tuple[str, shapely.Geometry]]:
    with settings.US_STATES_GEOJSON.open() as f:
        features = json.load(f)["features"]
    boundaries = []
    for feature in features:
        geometry = shape(feature["geometry"])
        shapely.prepare(geometry)
        boundaries.append((feature["properties"]["state"], geometry))
    return boundaries
