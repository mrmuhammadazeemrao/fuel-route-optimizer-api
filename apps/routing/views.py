from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView

from apps.routing.serializers import RouteRequestSerializer, RouteResponseSerializer
from apps.routing.services import plan_trip


def _plan_from(data) -> dict:
    serializer = RouteRequestSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return plan_trip(serializer.validated_data["start"], serializer.validated_data["finish"])


class RouteView(APIView):
    @extend_schema(
        request=RouteRequestSerializer,
        responses={
            200: RouteResponseSerializer,
            400: OpenApiResponse(description="Invalid or non-US location"),
            422: OpenApiResponse(description="No drivable route or no possible fuel plan"),
            503: OpenApiResponse(description="Routing service unavailable"),
        },
    )
    def post(self, request):
        trip = _plan_from(request.data)
        query = urlencode({"start": request.data["start"], "finish": request.data["finish"]})
        map_url = request.build_absolute_uri(f"{reverse('route-map')}?{query}")
        return Response(RouteResponseSerializer({**trip, "map_url": map_url}).data)


def route_map(request):
    """Leaflet map of the route and fuel stops for ?start=...&finish=... (same trip result)."""
    try:
        trip = _plan_from(request.GET)
    except APIException as exc:
        context = {"message": _error_message(exc)}
        return render(request, "routing/map_error.html", context, status=exc.status_code)
    return render(request, "routing/map.html", {"trip": trip})


def _error_message(exc: APIException) -> str:
    if isinstance(exc, ValidationError) and isinstance(exc.detail, dict):
        return " ".join(
            str(error) if field == api_settings.NON_FIELD_ERRORS_KEY else f"{field}: {error}"
            for field, errors in exc.detail.items()
            for error in errors
        )
    return str(exc.detail)
