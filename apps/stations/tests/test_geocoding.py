import pytest
import shapely

from apps.stations.geocoding.exits import ExitRef, parse_exit, parse_junctions, resolve_exit
from apps.stations.geocoding.geo import is_offshore
from apps.stations.geocoding.places import PlaceIndex, normalize

TEXAS = shapely.box(-98.0, 27.0, -97.3, 28.5)  # coastline along longitude -97.3


@pytest.mark.parametrize(
    "address, expected",
    [
        ("I-44, EXIT 283 & US-69", ExitRef("44", 283, "")),
        ("I-80 EXIT 78, & SR-36", ExitRef("80", 78, "")),
        ("I-70 Exit 57", ExitRef("70", 57, "")),
        ("I-35E, EXIT 421B", ExitRef("35", 421, "B")),
        ("I-80 E EXIT 110 & HWY169", ExitRef("80", 110, "")),
        ("I 95 EXIT #31", ExitRef("95", 31, "")),
        ("US-281", None),
        ("I-57 & SR-17", None),
    ],
)
def test_parse_exit(address, expected):
    assert parse_exit(address) == expected


def test_parse_junctions_groups_nodes_by_interstate():
    elements = [
        {"type": "way", "id": 1, "tags": {"ref": "I 35E;US 77"}},
        {"type": "node", "id": 10, "lat": 33.0, "lon": -97.0, "tags": {"ref": "421B"}},
        {"type": "way", "id": 2, "tags": {"ref": "I 35E"}},
        {"type": "node", "id": 10, "lat": 33.0, "lon": -97.0, "tags": {"ref": "421B"}},
        {"type": "way", "id": 3, "tags": {"ref": "I 44"}},
        {"type": "node", "id": 11, "lat": 36.5, "lon": -95.2, "tags": {"ref": "283"}},
    ]
    assert parse_junctions(elements) == {
        "35": [("421B", (33.0, -97.0))],
        "44": [("283", (36.5, -95.2))],
    }


BIG_CABIN = (36.5376, -95.2294)
JUNCTIONS = [
    ("283", (36.5679, -95.2134)),  # both directions of exit 283
    ("283", (36.5612, -95.2179)),
    ("289", (36.6200, -95.1500)),
    ("28", (36.0000, -96.0000)),
]


def test_resolve_exit_averages_both_directions():
    lat, lon = resolve_exit(ExitRef("44", 283, ""), JUNCTIONS, BIG_CABIN)
    assert lat == pytest.approx(36.5646, abs=1e-3)
    assert lon == pytest.approx(-95.2156, abs=1e-3)


def test_resolve_exit_rejects_exit_far_from_city():
    far_city = (40.0, -100.0)
    assert resolve_exit(ExitRef("44", 283, ""), JUNCTIONS, far_city) is None


def test_resolve_exit_prefers_exact_letter_suffix():
    junctions = [("421A", (33.0, -97.0)), ("421B", (33.01, -97.0))]
    assert resolve_exit(ExitRef("35", 421, "B"), junctions, (33.0, -97.0)) == (33.01, -97.0)


def test_resolve_exit_without_city_requires_unambiguous_cluster():
    junctions = [("10", (30.0, -90.0)), ("10", (35.0, -95.0))]
    assert resolve_exit(ExitRef("10", 10, ""), junctions, None) is None


@pytest.mark.parametrize(
    "a, b",
    [
        ("Saint Louis", "St. Louis"),
        ("Mc Calla", "McCalla"),
        ("Canon City", "Cañon City"),
        ("S Coffeyville", "South Coffeyville"),
        ("Ft Worth", "Fort Worth"),
        ("Mt Vernon", "Mount Vernon"),
    ],
)
def test_normalize_city_names(a, b):
    assert normalize(a) == normalize(b)


@pytest.mark.parametrize(
    "lat, lon, offshore",
    [
        (27.8, -97.5, False),  # inland
        (27.8, -97.297, False),  # ~0.2 miles off the (generalized) coast
        (27.754, -97.173, True),  # ~8 miles out
    ],
)
def test_is_offshore(lat, lon, offshore):
    assert is_offshore(TEXAS, lat, lon) is offshore


def test_place_index_replaces_internal_points_at_sea_with_gnis_town_centres(tmp_path):
    gazetteer = tmp_path / "places.txt"
    gazetteer.write_text(
        "USPS|GEOID|NAME|INTPTLAT|INTPTLONG\n"
        "TX|4817000|Corpus Christi city|27.754|-97.173\n"
        "TX|4863500|Robstown city|27.79|-97.67\n"
        "TX|4858904|Port Aransas city|27.83|-97.06\n"
    )
    gnis = tmp_path / "gnis.txt"
    gnis.write_text(
        "feature_name|feature_class|state_numeric|prim_lat_dec|prim_long_dec\n"
        "Corpus Christi|Populated Place|48|27.8006|-97.3964\n"
        "Robstown|Populated Place|48|27.7903|-97.6689\n"
    )
    places = PlaceIndex([gazetteer], gnis, land={"TX": TEXAS})

    assert places.lookup("Corpus Christi", "TX") == (27.8006, -97.3964)
    assert places.lookup("Robstown", "TX") == (27.79, -97.67)  # on land: Census point kept
    assert places.lookup("Port Aransas", "TX") == (27.83, -97.06)  # no GNIS place to use
