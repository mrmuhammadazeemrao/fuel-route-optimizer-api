from decimal import Decimal
from itertools import pairwise

import pytest

from apps.stations.index import _densify, _station_arrays, stations_along_route
from apps.stations.models import FuelStation


@pytest.fixture
def station_rows(db):
    _station_arrays.cache_clear()

    def create(*rows):
        FuelStation.objects.bulk_create(
            FuelStation(
                opis_id=i, name=f"S{i}", address="", city="", state="KS", rack_id=1,
                retail_price=Decimal("3.00"), latitude=lat, longitude=lon,
            )
            for i, (lat, lon) in enumerate(rows, 1)
        )  # fmt: skip

    yield create
    _station_arrays.cache_clear()


def test_densify_caps_spacing_and_keeps_total_length():
    lat, lon, miles = _densify([39.0, 39.0], [-100.0, -99.0], step=0.5)  # ~54 miles east
    assert miles[-1] == pytest.approx(53.7, abs=0.2)
    assert max(b - a for a, b in pairwise(miles)) <= 0.5 + 1e-9
    assert (lat[0], lon[0], lat[-1], lon[-1]) == (39.0, -100.0, 39.0, -99.0)


def test_stations_along_route_measures_mile_and_offset(station_rows):
    # Straight east-west route along 39N; 1 degree of longitude here is ~53.7 miles.
    station_rows(
        (39.0, -99.5),  # on the road, halfway
        (39.02, -99.0),  # ~1.4 miles north of the end point
        (39.2, -99.5),  # ~14 miles off the road
    )
    matches = stations_along_route([(39.0, -100.0), (39.0, -99.0)], max_off_route_miles=3)

    assert [m.station.name for m in matches] == ["S1", "S2"]
    assert matches[0].mile == pytest.approx(26.85, abs=0.3)
    assert matches[0].off_route_miles == pytest.approx(0, abs=0.01)
    assert matches[1].mile == pytest.approx(53.7, abs=0.3)
    assert matches[1].off_route_miles == pytest.approx(1.38, abs=0.05)
