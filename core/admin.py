from django.contrib import admin

from .models import Intersection, SystemLog, TrafficData, Weather


@admin.register(Intersection)
class IntersectionAdmin(admin.ModelAdmin):
    list_display = (
        "intersection_id", "area", "road", "latitude", "longitude",
        "coord_source", "num_approaches", "is_active",
    )
    list_filter = ("area", "coord_source", "is_active")
    search_fields = ("intersection_id", "area", "road")
    date_hierarchy = "created_at"


@admin.register(TrafficData)
class TrafficDataAdmin(admin.ModelAdmin):
    list_display = (
        "intersection", "recorded_date", "vehicle_count", "avg_speed_kph",
        "congestion_level", "source", "is_synthetic",
    )
    list_filter = ("source", "is_synthetic", "weather_condition")
    search_fields = ("intersection__intersection_id",)
    date_hierarchy = "recorded_date"
    raw_id_fields = ("intersection",)


@admin.register(Weather)
class WeatherAdmin(admin.ModelAdmin):
    list_display = (
        "recorded_at", "condition", "temp_celsius", "humidity",
        "wind_kph", "precipitation_mm", "source",
    )
    list_filter = ("condition", "source")
    date_hierarchy = "recorded_at"


@admin.register(SystemLog)
class SystemLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "level", "module", "message")
    list_filter = ("level", "module")
    search_fields = ("message", "module")
    date_hierarchy = "created_at"
    readonly_fields = ("level", "module", "message", "context", "created_at")
