import csv
from collections import Counter, defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.routing.locations import state_boundaries
from apps.stations.geocoding import sources
from apps.stations.geocoding.exits import fetch_state_junctions, parse_exit, resolve_exit
from apps.stations.geocoding.places import PlaceIndex
from apps.stations.models import FuelStation

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY",
}  # fmt: skip
Precision = FuelStation.GeocodePrecision


class Command(BaseCommand):
    help = (
        "One-time geocoding of US stations: interstate exits via OpenStreetMap (Overpass), "
        "everything else via city centroid (Census Gazetteer + USGS GNIS). "
        "Writes the database and exports data/station_coordinates.csv."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--all", action="store_true", help="Re-geocode every station, not only missing ones."
        )

    def handle(self, *args, all, **options):
        stations = FuelStation.objects.filter(state__in=US_STATES)
        if not all:
            stations = stations.filter(latitude__isnull=True)
        stations = list(stations)
        if not stations:
            self.stdout.write("Nothing to geocode.")
            self.export()
            return

        self.stdout.write("Building place index (Census Gazetteer + USGS GNIS)...")
        places = PlaceIndex(
            [
                sources.cached_zip_member(sources.GAZETTEER_PLACES_URL, ".txt"),
                sources.cached_zip_member(sources.GAZETTEER_COUSUBS_URL, ".txt"),
            ],
            sources.cached_zip_member(sources.GNIS_URL, ".txt"),
            land=dict(state_boundaries()),
        )

        exits = {s.pk: (s.state, ref) for s in stations if (ref := parse_exit(s.address))}
        junctions = self.fetch_junctions(exits)

        stats = Counter()
        for station in stations:
            city_point = places.lookup(station.city, station.state)
            exit_point = None
            if station.pk in exits:
                _, exit_ref = exits[station.pk]
                exit_point = resolve_exit(
                    exit_ref, junctions[station.state].get(exit_ref.interstate, []), city_point
                )

            if exit_point:
                station.latitude, station.longitude = exit_point
                station.geocode_precision = Precision.EXIT
            elif city_point:
                station.latitude, station.longitude = city_point
                station.geocode_precision = Precision.CITY
            else:
                station.latitude = station.longitude = None
                station.geocode_precision = ""
                stats["unresolved"] += 1
                self.stdout.write(f"  unresolved: {station.city}, {station.state}")
                continue
            stats[station.geocode_precision] += 1

        FuelStation.objects.bulk_update(
            stations, ["latitude", "longitude", "geocode_precision"], batch_size=1000
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Geocoded {len(stations) - stats['unresolved']}/{len(stations)} stations: "
                f"{stats[Precision.EXIT]} at exits, {stats[Precision.CITY]} at city centroids, "
                f"{stats['unresolved']} unresolved."
            )
        )
        self.export()

    def fetch_junctions(self, exits):
        states = sorted({state for state, _ in exits.values()})
        self.stdout.write(f"Fetching interstate exits from OpenStreetMap ({len(states)} states)...")
        junctions = defaultdict(dict)
        # Sequential on purpose: these queries are heavy and Overpass rate-limits per client.
        for done, state in enumerate(states, 1):
            junctions[state] = fetch_state_junctions(state)
            self.stdout.write(f"  [{done}/{len(states)}] {state}")
        return junctions

    def export(self):
        path = settings.STATION_COORDINATES_CSV
        rows = FuelStation.objects.filter(latitude__isnull=False).order_by("opis_id")
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["opis_id", "latitude", "longitude", "precision"])
            for s in rows.values_list("opis_id", "latitude", "longitude", "geocode_precision"):
                writer.writerow([s[0], f"{s[1]:.6f}", f"{s[2]:.6f}", s[3]])
        self.stdout.write(f"Exported {rows.count()} coordinates to {path.name}")
