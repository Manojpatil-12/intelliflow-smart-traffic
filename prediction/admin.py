from django.contrib import admin

from .models import Prediction


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = (
        "intersection", "target_date", "model_used", "predicted_volume",
        "congestion_level", "recommended_signal_seconds", "model_confidence",
        "feature_version", "created_at",
    )
    list_filter = ("model_used", "feature_version", "target_date")
    search_fields = ("intersection__intersection_id",)
    date_hierarchy = "target_date"
    raw_id_fields = ("intersection",)
