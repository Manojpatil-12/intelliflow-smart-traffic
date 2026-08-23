from django.contrib import admin

from .models import DetectionEvent


@admin.register(DetectionEvent)
class DetectionEventAdmin(admin.ModelAdmin):
    list_display = (
        "id", "intersection", "total_vehicles", "emergency_detected", "created_at",
    )
    list_filter = ("emergency_detected",)
    search_fields = ("intersection__intersection_id",)
    date_hierarchy = "created_at"
    raw_id_fields = ("intersection",)
