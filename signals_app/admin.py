from django.contrib import admin

from .models import EmergencyVehicle, SignalState


@admin.register(SignalState)
class SignalStateAdmin(admin.ModelAdmin):
    list_display = (
        "intersection", "current_state", "green_duration_seconds",
        "is_emergency_override", "updated_at",
    )
    list_filter = ("current_state", "is_emergency_override")
    search_fields = ("intersection__intersection_id",)
    raw_id_fields = ("intersection",)


@admin.register(EmergencyVehicle)
class EmergencyVehicleAdmin(admin.ModelAdmin):
    list_display = (
        "vehicle_type", "plate_number", "intersection",
        "detected_at", "route_cleared", "resolved_at",
    )
    list_filter = ("vehicle_type", "route_cleared")
    search_fields = ("plate_number", "intersection__intersection_id")
    date_hierarchy = "detected_at"
    raw_id_fields = ("intersection",)
