import shapely
from django.conf import settings

from apps.routing import osrm
from apps.routing.exceptions import NoFuelPlanAvailable
from apps.routing.fuel import Candidate, NoFuelPlan, plan_fuel_stops
from apps.routing.locations import Location
from apps.stations.index import stations_along_route

# Route line in the GeoJSON is simplified to ~50 m: a coast-to-coast route drops from
# ~35k to ~2.6k points. Station matching always uses the full-resolution route.
GEOJSON_SIMPLIFY_DEGREES = 0.0005


def plan_trip(start: Location, finish: Location) -> dict:
    """Route (one OSRM call) plus the cheapest fuel stops along it."""
    route = osrm.fetch_route(start, finish)

    on_route = stations_along_route(route.coordinates, settings.FUEL_STOP_MAX_OFF_ROUTE_MILES)
    candidates = [Candidate(s.mile, s.price, ref=s) for s in on_route]
    try:
        plan = plan_fuel_stops(
            candidates,
            trip_miles=route.distance_miles,
            range_miles=settings.VEHICLE_RANGE_MILES,
            mpg=settings.VEHICLE_MPG,
            stop_cost=settings.FUEL_STOP_COST_USD,
        )
    except NoFuelPlan as exc:
        raise NoFuelPlanAvailable(str(exc)) from exc

    stops = []
    for purchase in plan.purchases:
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
