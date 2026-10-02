import shapely
from django.conf import settings
from django.core.cache import cache

from apps.routing import osrm
from apps.routing.exceptions import NoFuelPlanAvailable
from apps.routing.fuel import Candidate, FuelPlan, NoFuelPlan, plan_fuel_stops
from apps.routing.locations import Location
from apps.stations.index import stations_along_route

# Route line in the GeoJSON is simplified to ~50 m: a coast-to-coast route drops from
# ~35k to ~2.6k points. Station matching always uses the full-resolution route.
GEOJSON_SIMPLIFY_DEGREES = 0.0005
# Alternative routes requested when the fastest route has no feasible fuel plan.
ALTERNATIVE_ROUTES = 2


def plan_trip(start: Location, finish: Location) -> dict:
    """Route plus the cheapest fuel stops along it, cached per start/finish pair.

    A cache miss costs one OSRM call (two in the rare case that the fastest route has no
    feasible fuel plan); a hit (e.g. the map page right after the API call, or a repeated
    request) costs none.
    """
    key = _cache_key(start, finish)
    trip = cache.get(key)
    if trip is None:
        trip = _plan_trip(start, finish)
        cache.set(key, trip)
    return trip


def _cache_key(start: Location, finish: Location) -> str:
    points = (
        f"{start.latitude:.5f},{start.longitude:.5f};{finish.latitude:.5f},{finish.longitude:.5f}"
    )
    knobs = (
        settings.VEHICLE_RANGE_MILES,
        settings.VEHICLE_MPG,
        settings.FUEL_STOP_COST_USD,
        settings.FUEL_STOP_MAX_OFF_ROUTE_MILES,
    )
    return f"trip:v1:{points}:{':'.join(map(str, knobs))}"


def _plan_trip(start: Location, finish: Location) -> dict:
    route = osrm.fetch_route(start, finish)
    try:
        plan = _plan_fuel(route)
    except NoFuelPlan as exc:
        route, plan = _plan_on_alternative_route(start, finish, exc)

    stops = []
    for purchase in plan.purchases:
        if round(purchase.gallons, 2) == 0:
            continue  # e.g. the only station is at the finish: nothing is left to buy there
        match = purchase.candidate.ref
        station = match.station
        stops.append(
            {
                "name": station.name,
                "address": station.address,
                "city": station.city,
                "state": station.state,
                "latitude": station.latitude,
                "longitude": station.longitude,
                "price_per_gallon": round(match.price, 3),
                "mile": round(match.mile, 1),
                "off_route_miles": round(match.off_route_miles, 1),
                "gallons": round(purchase.gallons, 2),
                "cost": round(purchase.cost, 2),
            }
        )

    return {
        "start": start,
        "finish": finish,
        "route": {
            "distance_miles": round(route.distance_miles, 1),
            "duration_hours": round(route.duration_hours, 2),
        },
        "fuel": {
            "total_cost": round(plan.total_cost, 2),
            "total_gallons": round(plan.total_gallons, 2),
            "initial_gallons": round(plan.initial_gallons, 2),
            "mpg": settings.VEHICLE_MPG,
            "range_miles": settings.VEHICLE_RANGE_MILES,
            "stops": stops,
        },
        "geojson": _geojson(route.coordinates, start, finish, stops),
    }


def _plan_fuel(route: osrm.Route) -> FuelPlan:
    on_route = stations_along_route(route.coordinates, settings.FUEL_STOP_MAX_OFF_ROUTE_MILES)
    return plan_fuel_stops(
        [Candidate(s.mile, s.price, ref=s) for s in on_route],
        trip_miles=route.distance_miles,
        range_miles=settings.VEHICLE_RANGE_MILES,
        mpg=settings.VEHICLE_MPG,
        stop_cost=settings.FUEL_STOP_COST_USD,
    )


def _plan_on_alternative_route(
    start: Location, finish: Location, error: NoFuelPlan
) -> tuple[osrm.Route, FuelPlan]:
    """First alternative route with a feasible fuel plan, from one more OSRM call.

    The fastest route can run 500+ miles without a station: Maine to California goes through
    Quebec and Ontario, and the price data has no stations there. Its alternative stays in the US.
    """
    for route in osrm.fetch_routes(start, finish, alternatives=ALTERNATIVE_ROUTES)[1:]:
        try:
            return route, _plan_fuel(route)
        except NoFuelPlan:
            continue
    raise NoFuelPlanAvailable(str(error)) from error


def _geojson(coordinates, start: Location, finish: Location, stops: list[dict]) -> dict:
    line = shapely.LineString([(lon, lat) for lat, lon in coordinates])
    line = line.simplify(GEOJSON_SIMPLIFY_DEGREES, preserve_topology=False)
    features = [
        _feature(
            "LineString",
            [[round(lon, 5), round(lat, 5)] for lon, lat in line.coords],
            {"kind": "route"},
        ),
        _feature("Point", [start.longitude, start.latitude], {"kind": "start", "name": start.name}),
        _feature(
            "Point", [finish.longitude, finish.latitude], {"kind": "finish", "name": finish.name}
        ),
    ]
    for number, stop in enumerate(stops, 1):
        properties = {"kind": "fuel_stop", "stop": number} | {
            k: stop[k] for k in ("name", "address", "price_per_gallon", "mile", "gallons", "cost")
        }
        features.append(_feature("Point", [stop["longitude"], stop["latitude"]], properties))
    return {"type": "FeatureCollection", "features": features}


def _feature(geometry_type: str, coordinates: list, properties: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": geometry_type, "coordinates": coordinates},
        "properties": properties,
    }
