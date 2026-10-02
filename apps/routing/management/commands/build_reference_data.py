import csv
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

import shapely
from django.conf import settings
from django.core.management.base import BaseCommand
from shapely import MultiPolygon, Polygon
from shapely.geometry import mapping

from apps.routing.locations import SUPPORTED_STATES
from apps.stations.geocoding import sources
from apps.stations.geocoding.geo import haversine_miles, is_offshore
from apps.stations.geocoding.places import normalize

KML = "{http://www.opengis.net/kml/2.2}"
# Case-sensitive: Census suffixes are lower case (except CDP), and "Carson City" keeps its "City".
_LSAD_SUFFIX = re.compile(
    r"\s+(city and borough|city|town|village|borough|CDP|municipality|corporation|"
    r"(consolidated|metro|metropolitan|unified) government|urban county)$"
)
# A populated place of the same name farther than this is a different place.
MAX_POPULATED_PLACE_MILES = 50

Point = tuple[float, float]


class Command(BaseCommand):
    help = (
        "Build the committed lookup files used to resolve start/finish locations: "
        "data/us_places.csv (Census Gazetteer places) and data/us_states.geojson "
        "(Census state boundaries). Only the lower 48 states + DC are kept."
    )

    def handle(self, *args, **options):
        land = self.build_states()
        self.build_places(land)

    def build_places(self, land: dict[str, shapely.Geometry]):
        source = sources.cached_zip_member(sources.GAZETTEER_PLACES_URL, ".txt")
        with source.open(encoding="utf-8-sig") as f:
            gazetteer = [
                row for row in csv.DictReader(f, delimiter="|") if row["USPS"] in SUPPORTED_STATES
            ]
        populated = _populated_places({row["GEOID"][:2]: row["USPS"] for row in gazetteer})

        rows, moved = [], 0
        for row in gazetteer:
            name = _LSAD_SUFFIX.sub("", row["NAME"].replace("(balance)", "").strip())
            state, lat, lon = row["USPS"], row["INTPTLAT"], row["INTPTLONG"]
            if is_offshore(land[state], float(lat), float(lon)):
                # The internal point is out in the place's water area (San Francisco's is 30 miles
                # out at sea, so routes started from the nearest road to it): use the USGS
                # populated place point, the town centre, instead.
                point = _nearest(populated[(normalize(name), state)], (float(lat), float(lon)))
                if point:
                    lat, lon = f"{point[0]:.6f}", f"{point[1]:.6f}"
                    moved += 1
            rows.append([name, state, lat, lon])

        with settings.US_PLACES_CSV.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "state", "latitude", "longitude"])
            writer.writerows(rows)
        self.stdout.write(
            f"Wrote {len(rows)} places to {settings.US_PLACES_CSV.name} "
            f"({moved} internal points out in the water replaced by USGS populated places)"
        )

    def build_states(self) -> dict[str, shapely.Geometry]:
        source = sources.cached_zip_member(sources.STATE_BOUNDARIES_URL, ".kml")
        features, land = [], {}
        for placemark in ET.parse(source).iter(f"{KML}Placemark"):
            state = placemark.find(f".//{KML}SimpleData[@name='STUSPS']").text
            if state not in SUPPORTED_STATES:
                continue
            polygons = [
                Polygon(
                    _ring(polygon.find(f"{KML}outerBoundaryIs")),
                    [_ring(inner) for inner in polygon.findall(f"{KML}innerBoundaryIs")],
                )
                for polygon in placemark.iter(f"{KML}Polygon")
            ]
            land[state] = MultiPolygon(polygons)
            features.append(
                {
                    "type": "Feature",
                    "properties": {"state": state},
                    "geometry": mapping(land[state]),
                }
            )
            shapely.prepare(land[state])

        with settings.US_STATES_GEOJSON.open("w") as f:
            json.dump({"type": "FeatureCollection", "features": features}, f, separators=(",", ":"))
        self.stdout.write(
            f"Wrote {len(features)} state boundaries to {settings.US_STATES_GEOJSON.name}"
        )
        return land


def _populated_places(fips_to_usps: dict[str, str]) -> dict[tuple[str, str], list[Point]]:
    """USGS GNIS populated place points by (normalized name, state)."""
    places = defaultdict(list)
    source = sources.cached_zip_member(sources.GNIS_URL, ".txt")
    with source.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter="|"):
            state = fips_to_usps.get(row["state_numeric"])
            if row["feature_class"] == "Populated Place" and state and row["prim_lat_dec"]:
                point = (float(row["prim_lat_dec"]), float(row["prim_long_dec"]))
                places[(normalize(row["feature_name"]), state)].append(point)
    return places


def _nearest(points: list[Point], target: Point) -> Point | None:
    point = min(points, key=lambda p: haversine_miles(*p, *target), default=None)
    if point and haversine_miles(*point, *target) <= MAX_POPULATED_PLACE_MILES:
        return point
    return None


def _ring(boundary) -> list[tuple[float, float]]:
    text = boundary.find(f".//{KML}coordinates").text
    return [
        (round(float(lon), 4), round(float(lat), 4))
        for lon, lat, *_ in (point.split(",") for point in text.split())
    ]
