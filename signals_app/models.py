from django.db import models

from core.models import Intersection


class SignalState(models.Model):
    STATE_CHOICES = [
        ("red", "Red"),
        ("yellow", "Yellow"),
        ("green", "Green"),
    ]
    intersection = models.OneToOneField(
        Intersection, on_delete=models.CASCADE, related_name="signal_state"
    )
    current_state = models.CharField(
        max_length=10, choices=STATE_CHOICES, default="green"
    )
    green_duration_seconds = models.IntegerField(default=45)
    is_emergency_override = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Signal state"
        verbose_name_plural = "Signal states"

    def __str__(self):
        return f"Signal: {self.intersection_id} [{self.current_state}]"


class EmergencyVehicle(models.Model):
    VEHICLE_TYPES = [
        ("ambulance", "Ambulance"),
        ("fire", "Fire Engine"),
        ("police", "Police"),
        ("other", "Other"),
    ]
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_TYPES)
    plate_number = models.CharField(max_length=20, blank=True, default="")
    intersection = models.ForeignKey(
        Intersection, on_delete=models.CASCADE, related_name="emergency_vehicles"
    )
    detected_at = models.DateTimeField(auto_now_add=True)
    route_cleared = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-detected_at"]

    def __str__(self):
        return f"{self.vehicle_type} @ {self.intersection_id} ({self.detected_at})"
