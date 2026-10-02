from rest_framework import serializers

from apps.routing.locations import FORMAT_HELP, LocationError, resolve_location


class LocationField(serializers.CharField):
    """Accepts "City, ST" or "lat,lon" and resolves it to a Location."""

    def __init__(self, **kwargs):
        super().__init__(max_length=200, help_text=FORMAT_HELP, **kwargs)

    def run_validation(self, data=serializers.empty):
        value = super().run_validation(data)  # string checks (required, blank, max_length)
        try:
            return resolve_location(value)
        except LocationError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class RouteRequestSerializer(serializers.Serializer):
    start = LocationField()
    finish = LocationField()

    def validate(self, attrs):
        start, finish = attrs["start"], attrs["finish"]
        if (start.latitude, start.longitude) == (finish.latitude, finish.longitude):
            raise serializers.ValidationError("Start and finish must be different locations.")
        return attrs


class LocationSerializer(serializers.Serializer):
    name = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class RouteSummarySerializer(serializers.Serializer):
    distance_miles = serializers.FloatField()
    duration_hours = serializers.FloatField()
    polyline = serializers.CharField(help_text="Encoded polyline (precision 6) of the route.")


class FuelStopSerializer(serializers.Serializer):
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    price_per_gallon = serializers.FloatField()
    mile = serializers.FloatField(help_text="Distance from the start along the route.")
    off_route_miles = serializers.FloatField()
    gallons = serializers.FloatField()
    cost = serializers.FloatField()


class FuelSummarySerializer(serializers.Serializer):
    total_cost = serializers.FloatField(help_text="USD for all fuel used on the trip.")
    total_gallons = serializers.FloatField(help_text="Trip distance / MPG.")
    initial_gallons = serializers.FloatField(
        help_text="Fuel used to reach the first stop (the tank starts empty), "
        "priced at the first stop and included in the totals."
    )
    mpg = serializers.FloatField()
    range_miles = serializers.FloatField()
    stops = FuelStopSerializer(many=True)


class RouteResponseSerializer(serializers.Serializer):
    start = LocationSerializer()
    finish = LocationSerializer()
    route = RouteSummarySerializer()
    fuel = FuelSummarySerializer()
