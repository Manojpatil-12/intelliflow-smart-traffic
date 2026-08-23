from django.db import models

from core.models import Intersection


class Prediction(models.Model):
    intersection = models.ForeignKey(
        Intersection, on_delete=models.CASCADE, related_name="predictions"
    )
    target_date = models.DateField()
    model_used = models.CharField(max_length=100)
    predicted_volume = models.FloatField(null=True, blank=True)
    congestion_level = models.FloatField(null=True, blank=True)
    class_probabilities = models.JSONField(null=True, blank=True)
    recommended_signal_seconds = models.IntegerField(null=True, blank=True)
    model_confidence = models.FloatField(null=True, blank=True)
    feature_version = models.CharField(max_length=20, null=True, blank=True)
    input_payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("intersection", "target_date", "model_used")
        ordering = ["-target_date", "intersection"]

    def __str__(self):
        return f"Prediction: {self.intersection_id} @ {self.target_date}"

    @property
    def congestion_class(self):
        if self.class_probabilities and "predicted_class" in self.class_probabilities:
            return self.class_probabilities["predicted_class"]
        return None
