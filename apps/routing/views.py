from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.routing.serializers import RouteRequestSerializer, RouteResponseSerializer
from apps.routing.services import plan_trip


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
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trip = plan_trip(serializer.validated_data["start"], serializer.validated_data["finish"])
        return Response(RouteResponseSerializer(trip).data)
