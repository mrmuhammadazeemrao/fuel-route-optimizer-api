from rest_framework import status
from rest_framework.exceptions import APIException


class NoRouteFound(APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "No drivable route found between start and finish."
    default_code = "no_route"


class RoutingUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The routing service is unavailable. Please try again shortly."
    default_code = "routing_unavailable"
