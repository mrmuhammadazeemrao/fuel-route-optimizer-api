from django.db import models


class FuelStation(models.Model):
    class GeocodePrecision(models.TextChoices):
        ADDRESS = "address", "Street address"
        CITY = "city", "City centroid"

    opis_id = models.PositiveIntegerField(unique=True, help_text="OPIS Truckstop ID")
    name = models.CharField(max_length=128)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.PositiveIntegerField()
    retail_price = models.DecimalField(max_digits=10, decimal_places=6, help_text="USD per gallon")

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    geocode_precision = models.CharField(
        max_length=16, choices=GeocodePrecision.choices, blank=True
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["opis_id"]
        indexes = [models.Index(fields=["latitude", "longitude"])]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state}) ${self.retail_price}"
