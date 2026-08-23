from django.db import models


class RawIngestionLog(models.Model):
    STATUS_CHOICES = [
        ("success", "Success"),
        ("error", "Error"),
        ("timeout", "Timeout"),
    ]
    source_name = models.CharField(max_length=50)
    endpoint = models.CharField(max_length=500)
    raw_payload = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    http_status = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    latency_ms = models.FloatField(null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fetched_at"]
        verbose_name = "Raw ingestion log"
        verbose_name_plural = "Raw ingestion logs"

    def __str__(self):
        return f"{self.source_name} [{self.status}] @ {self.fetched_at}"
