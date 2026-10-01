from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.stations.models import FuelStation

CSV = """OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price
20,PILOT TRAVEL CENTER #1243,"I-8, EXIT 119 & SR-85",Gila Bend,AZ,930,3.899
20,PILOT #1243,"I-8, EXIT 119 & SR-85",Gila Bend,AZ,930,3.799
7,WOODSHED OF BIG CABIN,"I-44, EXIT 283 & US-69",Big Cabin,OK,307,3.00733333
"""


@pytest.fixture
def csv_path(tmp_path, settings):
    settings.STATION_COORDINATES_CSV = tmp_path / "missing.csv"
    path = tmp_path / "prices.csv"
    path.write_text(CSV)
    return path


@pytest.mark.django_db
def test_merges_duplicates_keeping_cheapest_price(csv_path):
    call_command("load_stations", path=csv_path)

    assert FuelStation.objects.count() == 2
    pilot = FuelStation.objects.get(opis_id=20)
    assert pilot.retail_price == Decimal("3.799")
    assert pilot.name == "PILOT #1243"


@pytest.mark.django_db
def test_reimport_updates_price_and_keeps_coordinates(csv_path):
    call_command("load_stations", path=csv_path)
    FuelStation.objects.filter(opis_id=7).update(latitude=36.5, longitude=-95.2)

    csv_path.write_text(CSV.replace("3.00733333", "2.95"))
    call_command("load_stations", path=csv_path)

    station = FuelStation.objects.get(opis_id=7)
    assert station.retail_price == Decimal("2.95")
    assert (station.latitude, station.longitude) == (36.5, -95.2)


@pytest.mark.django_db
def test_applies_coordinates_file(csv_path, tmp_path):
    coords = tmp_path / "coords.csv"
    coords.write_text("opis_id,latitude,longitude,precision\n7,36.564600,-95.215600,exit\n")

    call_command("load_stations", path=csv_path, coordinates=coords)

    station = FuelStation.objects.get(opis_id=7)
    assert (station.latitude, station.longitude) == (36.5646, -95.2156)
    assert station.geocode_precision == FuelStation.GeocodePrecision.EXIT
    assert FuelStation.objects.get(opis_id=20).latitude is None
