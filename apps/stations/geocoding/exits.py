"""Pin "I-44, EXIT 283"-style addresses to the interchange using OpenStreetMap motorway junctions.

Exit numbers are unique per interstate within a state, so for every state one Overpass query
returns each interstate motorway segment that carries junctions (``highway=motorway_junction``
with a ``ref``), followed by those junction nodes. Responses are cached per state.
"""

import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass

import requests
from django.conf import settings

from apps.stations.geocoding.geo import haversine_miles, mean_point
from apps.stations.geocoding.sources import USER_AGENT

logger = logging.getLogger(__name__)

Point = tuple[float, float]
Junctions = dict[str, list[tuple[str, Point]]]  # interstate number -> [(exit ref, point)]

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# A station listed under a town is rarely more than this far from the exit it names.
MAX_EXIT_TO_CITY_MILES = 25
# Junction nodes for one exit (both directions, ramps) sit within this distance of each other.
SAME_EXIT_MILES = 3

# "I-44, EXIT 283", "I-80 EXIT 78", "I-35E Exit 421B", "I 95 EXIT #31"
_EXIT_RE = re.compile(r"\bI[- ]?(\d{1,3})(?:[EWC]\b)?[^&]*?\bEXIT\s*#?\s*(\d{1,3})([A-Z]?)\b", re.I)
# Interstate numbers in an OSM way ref such as "I 35E;US 77"
_OSM_INTERSTATE_RE = re.compile(r"(?:^|;)\s*I[- ]?(\d{1,3})")

_QUERY = (
    '[out:json][timeout:600];area["ISO3166-2"="US-{state}"]->.s;'
    'way(area.s)[highway=motorway][ref~"(^|;) *I[- ]?[0-9]"]->.w;'
    "node(w.w)[highway=motorway_junction][ref]->.j;"
    "way.w(bn.j)->.x;"
    "foreach.x->.y(.y out tags;node.j(w.y);out;);"
)


@dataclass(frozen=True)
class ExitRef:
    interstate: str  # "44"
    number: int  # 283
    suffix: str  # "" or "A"


def parse_exit(address: str) -> ExitRef | None:
    match = _EXIT_RE.search(address)
    if not match:
        return None
    return ExitRef(match.group(1), int(match.group(2)), match.group(3).upper())


def fetch_state_junctions(state: str, retries: int = 6) -> Junctions:
    """Interstate exit junctions of one state, from cache or a single Overpass query."""
    cache = settings.GEOCODING_CACHE_DIR / "overpass" / f"{state}.json"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(_query_overpass(state, retries)))
    return parse_junctions(json.loads(cache.read_text()))


def _query_overpass(state: str, retries: int) -> list[dict]:
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(
                OVERPASS_URL,
                data={"data": _QUERY.format(state=state)},
                headers={"User-Agent": USER_AGENT},
                timeout=630,
            )
            response.raise_for_status()
            return response.json()["elements"]
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Overpass failed for %s (attempt %d): %s", state, attempt, exc)
            time.sleep(30 * attempt)
    raise RuntimeError(f"Overpass failed for {state} after {retries} attempts")


def parse_junctions(elements: list[dict]) -> Junctions:
    """Elements come as: way (tags only), then that way's junction nodes, repeated."""
    junctions: Junctions = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    interstates: list[str] = []
    for element in elements:
        if element["type"] == "way":
            interstates = _OSM_INTERSTATE_RE.findall(element.get("tags", {}).get("ref", ""))
        elif element["type"] == "node":
            for num in interstates:
                if (num, element["id"]) not in seen:
                    seen.add((num, element["id"]))
                    point = (element["lat"], element["lon"])
                    junctions[num].append((element["tags"]["ref"], point))
    return junctions


def _ref_matches(osm_ref: str, exit_ref: ExitRef) -> int:
    """0 = no match, 1 = same exit number, 2 = exact match including letter suffix."""
    match = re.match(r"\s*(\d+)\s*([A-Z]?)", osm_ref.upper())
    if not match or int(match.group(1)) != exit_ref.number:
        return 0
    return 2 if exit_ref.suffix and match.group(2) == exit_ref.suffix else 1


def resolve_exit(
    exit_ref: ExitRef, junctions: list[tuple[str, Point]], city_point: Point | None
) -> Point | None:
    """Pick the junction(s) for this exit, using the station's city to disambiguate."""
    scored = [(_ref_matches(ref, exit_ref), point) for ref, point in junctions]
    best = max((score for score, _ in scored), default=0)
    candidates = [point for score, point in scored if score == best and score > 0]
    if not candidates:
        return None

    if city_point:
        candidates = [
            p for p in candidates if haversine_miles(*p, *city_point) <= MAX_EXIT_TO_CITY_MILES
        ]
        if not candidates:
            return None
        anchor = min(candidates, key=lambda p: haversine_miles(*p, *city_point))
    else:
        anchor = candidates[0]

    cluster = [p for p in candidates if haversine_miles(*p, *anchor) <= SAME_EXIT_MILES]
    if not city_point and len(cluster) != len(candidates):
        return None  # same exit number in several places and nothing to tell them apart
    return mean_point(cluster)
