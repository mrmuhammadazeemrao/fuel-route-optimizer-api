from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.routing import osrm
from apps.routing.serializers import RouteRequestSerializer, RouteResponseSerializer


class RouteView(APIView):
    @extend_schema(
        request=RouteRequestSerializer,
        responses={
            200: RouteResponseSerializer,
            400: OpenApiResponse(description="Invalid or non-US location"),
            422: OpenApiResponse(description="No drivable route"),
            503: OpenApiResponse(description="Routing service unavailable"),
        },
    )
    def post(self, request):
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        start, finish = serializer.validated_data["start"], serializer.validated_data["finish"]

        route = osrm.fetch_route(start, finish)

        payload = {
            "start": start,
            "finish": finish,
            "route": {
                "distance_miles": round(route.distance_miles, 1),
                "duration_hours": round(route.duration_hours, 2),
                "polyline": route.polyline,
            },
        }
        return Response(RouteResponseSerializer(payload).data)
