import pytest

from apps.routing.locations import LocationError, resolve_location


@pytest.mark.parametrize(
    "query, name",
    [
        ("Chicago, IL", "Chicago, IL"),
        ("new york, ny", "New York, NY"),
        ("Saint Louis, MO", "St. Louis, MO"),
        ("Nashville, TN", "Nashville-Davidson, TN"),
        ("41.8781,-87.6298", "41.87810,-87.62980 (IL)"),
        (" 47.6062 , -122.3321 ", "47.60620,-122.33210 (WA)"),
    ],
)
def test_resolves_us_locations(query, name):
    assert resolve_location(query).name == name


@pytest.mark.parametrize(
    "query, error",
    [
        ("42.3149,-83.0364", "outside the contiguous United States"),  # Windsor, Canada
        ("31.6904,-106.4245", "outside the contiguous United States"),  # Juarez, Mexico
        ("-87.6298,41.8781", "outside the contiguous United States"),  # lon,lat swapped
        ("21.3069,-157.8583", "outside the contiguous United States"),  # Honolulu
        ("95,10", "Invalid coordinates"),
        ("Anchorage, AK", "AK is not supported"),
        ("Toronto, ON", "Unknown US state code"),
        ("Nowhere, TX", "not found"),
        ("Chicago", "Unrecognized location"),
    ],
)
def test_rejects_invalid_or_non_us_locations(query, error):
    with pytest.raises(LocationError, match=error):
        resolve_location(query)
