from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.stations.models import FuelStation


@extend_schema(responses={200: dict})
@api_view(["GET"])
def health(request):
    """Liveness check: confirms the database is reachable and reports station data status."""
    connection.ensure_connection()
    return Response(
        {
            "status": "ok",
            "stations": FuelStation.objects.count(),
            "geocoded_stations": FuelStation.objects.filter(latitude__isnull=False).count(),
        }
    )
