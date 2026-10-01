from unittest.mock import Mock, patch

import polyline
import pytest
import requests
from django.urls import reverse

COORDS = [(41.837045, -87.684939), (35.0, -91.0), (29.785743, -95.388806)]
OSRM_OK = {
    "code": "Ok",
    "routes": [
        {"distance": 1_743_000.0, "duration": 71_600.0, "geometry": polyline.encode(COORDS, 6)}
    ],
}


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


def test_route_success_makes_one_osrm_call(client):
    with osrm_returns(OSRM_OK) as get:
        response = post(client)

    assert response.status_code == 200
    body = response.json()
    assert body["start"]["name"] == "Chicago, IL"
    assert body["finish"]["name"] == "Houston, TX"
    assert body["route"]["distance_miles"] == 1083.0
    assert body["route"]["duration_hours"] == 19.89
    assert polyline.decode(body["route"]["polyline"], 6) == COORDS

    get.assert_called_once()
    url = get.call_args.args[0]
    assert url.endswith("/route/v1/driving/-87.684939,41.837045;-95.388806,29.785743")


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
