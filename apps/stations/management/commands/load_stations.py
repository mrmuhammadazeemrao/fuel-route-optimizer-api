import csv
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.stations.models import FuelStation

UPDATE_FIELDS = ["name", "address", "city", "state", "rack_id", "retail_price"]
COORDINATE_FIELDS = ["latitude", "longitude", "geocode_precision"]


class Command(BaseCommand):
    help = (
        "Import fuel stations from the OPIS CSV. Rows sharing a Truckstop ID are merged, "
        "keeping the cheapest price. Coordinates are applied from the pre-geocoded CSV "
        "(see `geocode_stations`); re-running updates prices but keeps existing coordinates."
    )

    def add_arguments(self, parser):
        parser.add_argument("--path", type=Path, default=settings.FUEL_PRICES_CSV)
        parser.add_argument("--coordinates", type=Path, default=settings.STATION_COORDINATES_CSV)

    def handle(self, *args, path, coordinates, **options):
        if not path.exists():
            raise CommandError(f"CSV not found: {path}")

        stations: dict[int, FuelStation] = {}
        with path.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))

        for row in rows:
            station = FuelStation(
                opis_id=int(row["OPIS Truckstop ID"]),
                name=row["Truckstop Name"].strip(),
                address=row["Address"].strip(),
                city=row["City"].strip(),
                state=row["State"].strip().upper(),
                rack_id=int(row["Rack ID"]),
                retail_price=Decimal(row["Retail Price"]),
            )
            existing = stations.get(station.opis_id)
            if existing is None or station.retail_price < existing.retail_price:
                stations[station.opis_id] = station

        FuelStation.objects.bulk_create(
            stations.values(),
            batch_size=1000,
            update_conflicts=True,
            unique_fields=["opis_id"],
            update_fields=UPDATE_FIELDS,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Loaded {len(stations)} unique stations from {len(rows)} rows.")
        )

        if coordinates.exists():
            self.apply_coordinates(coordinates)

    def apply_coordinates(self, path: Path):
        with path.open(newline="") as f:
            coords = {int(r["opis_id"]): r for r in csv.DictReader(f)}

        stations = list(FuelStation.objects.filter(opis_id__in=coords))
        for station in stations:
            row = coords[station.opis_id]
            station.latitude = float(row["latitude"])
            station.longitude = float(row["longitude"])
            station.geocode_precision = row["precision"]
        FuelStation.objects.bulk_update(stations, COORDINATE_FIELDS, batch_size=1000)
        self.stdout.write(
            self.style.SUCCESS(f"Applied coordinates to {len(stations)} stations from {path.name}.")
        )
