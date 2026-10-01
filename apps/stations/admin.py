from django.contrib import admin

from apps.stations.models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ["opis_id", "name", "city", "state", "retail_price", "geocode_precision"]
    list_filter = ["state", "geocode_precision"]
    search_fields = ["name", "city", "address"]
