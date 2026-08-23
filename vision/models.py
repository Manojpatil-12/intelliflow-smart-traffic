from django.db import models

from core.models import Intersection


class DetectionEvent(models.Model):
    intersection = models.ForeignKey(
        Intersection, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="detection_events"
    )
    image = models.ImageField(upload_to="detections/")
    annotated_image = models.ImageField(
        upload_to="detections/annotated/", null=True, blank=True
    )
    counts = models.JSONField(default=dict)
    total_vehicles = models.IntegerField(default=0)
    emergency_detected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Detection #{self.pk} — {self.total_vehicles} vehicles @ {self.created_at}"
