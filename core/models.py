from django.db import models


class Intersection(models.Model):
    intersection_id = models.CharField(max_length=200, unique=True)
    area = models.CharField(max_length=100)
    road = models.CharField(max_length=200)
    latitude = models.FloatField()
    longitude = models.FloatField()
    coord_source = models.CharField(max_length=50, default="curated")
    num_approaches = models.IntegerField(default=4)
    default_green_seconds = models.IntegerField(default=45)
    hist_mean_volume = models.FloatField(null=True, blank=True)
    hist_mean_congestion = models.FloatField(null=True, blank=True)
    hist_severe_rate = models.FloatField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["area", "road"]

    def __str__(self):
        return self.intersection_id


class TrafficData(models.Model):
    SOURCE_CHOICES = [
        ("dataset", "Dataset"),
        ("live", "Live"),
        ("camera", "Camera"),
        ("manual", "Manual"),
    ]
    intersection = models.ForeignKey(
        Intersection, on_delete=models.CASCADE, related_name="traffic_data"
    )
    recorded_date = models.DateField()
    vehicle_count = models.FloatField(null=True, blank=True)
    avg_speed_kph = models.FloatField(null=True, blank=True)
    travel_time_index = models.FloatField(null=True, blank=True)
    congestion_level = models.FloatField(null=True, blank=True)
    capacity_utilization = models.FloatField(null=True, blank=True)
    incident_reports = models.FloatField(null=True, blank=True)
    env_impact = models.FloatField(null=True, blank=True)
    pt_usage = models.FloatField(null=True, blank=True)
    signal_compliance = models.FloatField(null=True, blank=True)
    parking_usage = models.FloatField(null=True, blank=True)
    ped_count = models.FloatField(null=True, blank=True)
    weather_condition = models.CharField(max_length=50, null=True, blank=True)
    roadwork = models.CharField(max_length=10, null=True, blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="dataset")
    is_synthetic = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("intersection", "recorded_date")
        indexes = [
            models.Index(fields=["intersection", "-recorded_date"]),
        ]
        ordering = ["-recorded_date"]
        verbose_name_plural = "Traffic data"

    def __str__(self):
        return f"{self.intersection_id} @ {self.recorded_date}"


class Weather(models.Model):
    recorded_at = models.DateTimeField()
    latitude = models.FloatField()
    longitude = models.FloatField()
    temp_celsius = models.FloatField(null=True, blank=True)
    humidity = models.FloatField(null=True, blank=True)
    condition = models.CharField(max_length=50, null=True, blank=True)
    wind_kph = models.FloatField(null=True, blank=True)
    visibility_km = models.FloatField(null=True, blank=True)
    precipitation_mm = models.FloatField(null=True, blank=True)
    source = models.CharField(max_length=50, default="openmeteo")

    class Meta:
        ordering = ["-recorded_at"]
        verbose_name_plural = "Weather records"

    def __str__(self):
        return f"Weather @ {self.recorded_at}"


class SystemLog(models.Model):
    LEVEL_CHOICES = [
        ("DEBUG", "Debug"),
        ("INFO", "Info"),
        ("WARNING", "Warning"),
        ("ERROR", "Error"),
        ("CRITICAL", "Critical"),
    ]
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default="INFO")
    module = models.CharField(max_length=100)
    message = models.TextField()
    context = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.level}] {self.module}: {self.message[:80]}"
