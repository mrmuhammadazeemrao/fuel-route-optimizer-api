from django.urls import path

from apps.routing.views import RouteView, route_map

urlpatterns = [
    path("route/", RouteView.as_view(), name="route"),
    path("route/map/", route_map, name="route-map"),
]
