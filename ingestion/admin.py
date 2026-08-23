from django.contrib import admin

from .models import RawIngestionLog


@admin.register(RawIngestionLog)
class RawIngestionLogAdmin(admin.ModelAdmin):
    list_display = (
        "source_name", "endpoint", "status", "http_status",
        "latency_ms", "fetched_at",
    )
    list_filter = ("source_name", "status")
    search_fields = ("endpoint", "error_message")
    date_hierarchy = "fetched_at"
    readonly_fields = (
        "source_name", "endpoint", "raw_payload", "status",
        "http_status", "error_message", "latency_ms", "fetched_at",
    )
