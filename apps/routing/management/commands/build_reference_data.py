import csv
import json
import re
import xml.etree.ElementTree as ET

from django.conf import settings
from django.core.management.base import BaseCommand
from shapely import MultiPolygon, Polygon
from shapely.geometry import mapping

from apps.routing.locations import SUPPORTED_STATES
from apps.stations.geocoding import sources

KML = "{http://www.opengis.net/kml/2.2}"
_LSAD_SUFFIX = re.compile(
    r"\s+(city and borough|city|town|village|borough|CDP|municipality|"
    r"(consolidated|metropolitan|unified) government|urban county)$",
    re.I,
)


class Command(BaseCommand):
    help = (
        "Build the committed lookup files used to resolve start/finish locations: "
        "data/us_places.csv (Census Gazetteer places) and data/us_states.geojson "
        "(Census state boundaries). Only the lower 48 states + DC are kept."
    )

    def handle(self, *args, **options):
        self.build_places()
        self.build_states()

    def build_places(self):
        source = sources.cached_zip_member(sources.GAZETTEER_PLACES_URL, ".txt")
        rows = []
        with source.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="|"):
                if row["USPS"] not in SUPPORTED_STATES:
                    continue
                name = _LSAD_SUFFIX.sub("", row["NAME"].replace("(balance)", "").strip())
                rows.append([name, row["USPS"], row["INTPTLAT"], row["INTPTLONG"]])

        with settings.US_PLACES_CSV.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "state", "latitude", "longitude"])
            writer.writerows(rows)
        self.stdout.write(f"Wrote {len(rows)} places to {settings.US_PLACES_CSV.name}")

    def build_states(self):
        source = sources.cached_zip_member(sources.STATE_BOUNDARIES_URL, ".kml")
        features = []
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
            features.append(
                {
                    "type": "Feature",
                    "properties": {"state": state},
                    "geometry": mapping(MultiPolygon(polygons)),
                }
            )

        with settings.US_STATES_GEOJSON.open("w") as f:
            json.dump({"type": "FeatureCollection", "features": features}, f, separators=(",", ":"))
        self.stdout.write(
            f"Wrote {len(features)} state boundaries to {settings.US_STATES_GEOJSON.name}"
        )


def _ring(boundary) -> list[tuple[float, float]]:
    text = boundary.find(f".//{KML}coordinates").text
    return [
        (round(float(lon), 4), round(float(lat), 4))
        for lon, lat, *_ in (point.split(",") for point in text.split())
    ]
