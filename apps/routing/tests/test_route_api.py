from decimal import Decimal
from itertools import pairwise
from unittest.mock import Mock, patch

import polyline
import pytest
import requests
from django.core.cache import cache
from django.urls import reverse

from apps.stations.geocoding.geo import haversine_miles
from apps.stations.index import _station_arrays
from apps.stations.models import FuelStation

# Chicago -> Houston, simplified to 5 points (~1,020 miles).
COORDS = [
    (41.837045, -87.684939),
    (38.6, -89.5),
    (35.0, -91.0),
    (32.3, -93.3),
    (29.785743, -95.388806),
]
ROUTE_MILES = sum(haversine_miles(*a, *b) for a, b in pairwise(COORDS))
OSRM_OK = {
    "code": "Ok",
    "routes": [
        {
            "distance": ROUTE_MILES * 1609.344,
            "duration": 70_000.0,
            "geometry": polyline.encode(COORDS, 6),
        }
    ],
}


@pytest.fixture(autouse=True)
def stations(db):
    _station_arrays.cache_clear()
    cache.clear()
    rows = [
        (1, "START", 41.837045, -87.684939, "3.50"),
        (2, "SOUTH IL", 38.6, -89.5, "3.40"),
        (3, "ARKANSAS", 35.0, -91.0, "3.00"),
        (4, "LOUISIANA", 32.3, -93.3, "3.20"),
        (5, "FAR AWAY CHEAP", 40.0, -100.0, "2.00"),  # nowhere near the route
    ]
    FuelStation.objects.bulk_create(
        FuelStation(
            opis_id=opis_id, name=name, address="I-55", city="X", state="IL", rack_id=1,
            retail_price=Decimal(price), latitude=lat, longitude=lon, geocode_precision="exit",
        )
        for opis_id, name, lat, lon, price in rows
    )  # fmt: skip
    yield
    _station_arrays.cache_clear()


def osrm_returns(payload=None, status=200, exc=None):
    mock = Mock()
    if exc:
        mock.side_effect = exc
    else:
        mock.return_value = Mock(status_code=status, json=Mock(return_value=payload))
    return patch("apps.routing.osrm._session.get", mock)


def post(client, start="Chicago, IL", finish="Houston, TX"):
    return client.post(
        reverse("route"), {"start": start, "finish": finish}, content_type="application/json"
    )


def test_route_with_fuel_plan_makes_one_osrm_call(client):
    with osrm_returns(OSRM_OK) as get:
        response = post(client)

    assert response.status_code == 200
    body = response.json()
    assert body["start"]["name"] == "Chicago, IL"
    assert body["finish"]["name"] == "Houston, TX"
    assert body["route"]["distance_miles"] == round(ROUTE_MILES, 1)

    fuel = body["fuel"]
    names = [s["name"] for s in fuel["stops"]]
    assert names[0] == "START"
    assert "FAR AWAY CHEAP" not in names
    assert "ARKANSAS" in names  # the cheapest station on the route
    assert fuel["total_gallons"] == pytest.approx(ROUTE_MILES / 10, abs=0.01)
    assert fuel["total_cost"] == pytest.approx(sum(s["cost"] for s in fuel["stops"]), abs=0.05)
    assert all(s["gallons"] <= 50 for s in fuel["stops"])
    legs = [b["mile"] - a["mile"] for a, b in pairwise(fuel["stops"])]
    assert max([*legs, ROUTE_MILES - fuel["stops"][-1]["mile"]]) <= 500

    get.assert_called_once()
    url = get.call_args.args[0]
    assert url.endswith("/route/v1/driving/-87.684939,41.837045;-95.388806,29.785743")


def test_no_stations_along_route_returns_422(client):
    FuelStation.objects.exclude(name="FAR AWAY CHEAP").delete()
    with osrm_returns(OSRM_OK):
        response = post(client)
    assert response.status_code == 422
    assert response.json()["detail"] == "No fuel stations found along the route."


def test_invalid_location_returns_400_without_calling_osrm(client):
    with osrm_returns(OSRM_OK) as get:
        response = post(client, start="Toronto, ON")

    assert response.status_code == 400
    assert "start" in response.json()
    get.assert_not_called()


def test_same_start_and_finish_returns_400(client):
    with osrm_returns(OSRM_OK):
        response = post(client, finish="Chicago, IL")
    assert response.status_code == 400


def test_no_route_returns_422(client):
    with osrm_returns({"code": "NoRoute", "message": "Impossible route"}, status=400):
        response = post(client)
    assert response.status_code == 422
    assert response.json()["detail"] == "No drivable route found between start and finish."


@pytest.mark.parametrize(
    "mock_kwargs",
    [
        {"exc": requests.Timeout()},
        {"exc": requests.ConnectionError()},
        {"payload": {"code": "TooBig"}, "status": 400},
    ],
)
def test_routing_service_failure_returns_503(client, mock_kwargs):
    with osrm_returns(**mock_kwargs):
        response = post(client)
    assert response.status_code == 503


def test_non_json_response_returns_503(client):
    response_mock = Mock(status_code=429, json=Mock(side_effect=ValueError("not json")))
    with patch("apps.routing.osrm._session.get", return_value=response_mock):
        response = post(client)
    assert response.status_code == 503


def test_response_includes_geojson_and_map_url(client):
    with osrm_returns(OSRM_OK):
        body = post(client).json()

    features = body["geojson"]["features"]
    kinds = [f["properties"]["kind"] for f in features]
    assert kinds[:3] == ["route", "start", "finish"]
    assert kinds.count("fuel_stop") == len(body["fuel"]["stops"])
    route_line = features[0]["geometry"]
    assert route_line["type"] == "LineString"
    assert route_line["coordinates"][0] == pytest.approx(
        [-87.684939, 41.837045], abs=1e-5
    )  # lon, lat
    assert body["map_url"] == (
        "http://testserver/api/v1/route/map/?start=Chicago%2C+IL&finish=Houston%2C+TX"
    )


def test_map_page_renders_route_and_stops(client):
    with osrm_returns(OSRM_OK):
        response = client.get(
            reverse("route-map"), {"start": "Chicago, IL", "finish": "Houston, TX"}
        )

    assert response.status_code == 200
    html = response.content.decode()
    assert "leaflet" in html
    assert '<script id="trip-geojson" type="application/json">' in html
    assert "Chicago, IL → Houston, TX" in html


def test_map_page_shows_validation_errors(client):
    response = client.get(reverse("route-map"), {"start": "Toronto, ON", "finish": "Houston, TX"})
    assert response.status_code == 400
    assert "Unknown US state code" in response.content.decode()


def test_repeated_request_is_served_from_cache(client):
    with osrm_returns(OSRM_OK) as get:
        first = post(client).json()
        second = post(client, start="chicago, il", finish="Houston, TX").json()

    get.assert_called_once()
    assert second.pop("map_url") != first.pop("map_url")  # echoes each request's own input
    assert second == first


def test_map_after_api_call_makes_no_extra_routing_call(client):
    with osrm_returns(OSRM_OK) as get:
        map_url = post(client).json()["map_url"]
        response = client.get(map_url)

    assert response.status_code == 200
    get.assert_called_once()


def test_routing_errors_are_not_cached(client):
    with osrm_returns(exc=requests.Timeout()):
        assert post(client).status_code == 503
    with osrm_returns(OSRM_OK) as get:
        assert post(client).status_code == 200
    get.assert_called_once()
