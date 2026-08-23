"""Scheduled jobs for data ingestion and prediction."""

import logging
from datetime import date, timedelta, timezone as dt_tz

from django.utils import timezone

from core.models import Intersection, SystemLog, TrafficData

logger = logging.getLogger("ingestion.jobs")


def ingest_traffic():
    """Fetch traffic data from TomTom for all active intersections."""
    from .tomtom import fetch_traffic_flow

    intersections = Intersection.objects.filter(is_active=True)
    success = 0
    failed = 0

    for ix in intersections:
        result = fetch_traffic_flow(ix)
        if result:
            # Store as live TrafficData
            today = date.today()
            speed = result.get("current_speed")
            free_flow = result.get("free_flow_speed")
            congestion = None
            if speed and free_flow and free_flow > 0:
                congestion = max(0, min(100, (1 - speed / free_flow) * 100))

            TrafficData.objects.update_or_create(
                intersection=ix,
                recorded_date=today,
                defaults={
                    "avg_speed_kph": speed,
                    "congestion_level": congestion,
                    "source": "live",
                },
            )
            success += 1
        else:
            failed += 1

    logger.info("Traffic ingestion: %d OK, %d failed", success, failed)
    SystemLog.objects.create(
        level="INFO" if failed == 0 else "WARNING",
        module="ingestion",
        message=f"Traffic ingestion: {success} OK, {failed} failed",
    )


def ingest_weather():
    """Fetch weather from Open-Meteo."""
    from .openmeteo import fetch_weather

    result = fetch_weather()
    if result:
        logger.info("Weather ingestion OK: %s", result.get("condition"))
    else:
        logger.warning("Weather ingestion failed")
        SystemLog.objects.create(
            level="WARNING",
            module="ingestion",
            message="Weather ingestion failed",
        )


def run_daily_predictions():
    """Run predictions for tomorrow for all active intersections."""
    from prediction.registry import registry

    if not registry.is_healthy():
        logger.error("Cannot run predictions — registry unhealthy")
        SystemLog.objects.create(
            level="ERROR",
            module="prediction",
            message="Scheduled predictions skipped — registry unhealthy",
        )
        return

    tomorrow = date.today() + timedelta(days=1)
    intersections = Intersection.objects.filter(is_active=True)
    success = 0
    errors = 0

    for ix in intersections:
        try:
            registry.predict(ix, tomorrow)
            success += 1
        except Exception as e:
            errors += 1
            logger.error("Prediction failed for %s: %s", ix.intersection_id, e)

    SystemLog.objects.create(
        level="INFO" if errors == 0 else "WARNING",
        module="prediction",
        message=f"Daily predictions for {tomorrow}: {success} OK, {errors} errors",
    )


def refresh_overpass():
    """Weekly refresh of road network data."""
    from .overpass import fetch_road_network

    result = fetch_road_network()
    if result:
        logger.info("Overpass refresh: %d elements", len(result))
        SystemLog.objects.create(
            level="INFO",
            module="ingestion",
            message=f"Overpass refresh: {len(result)} road elements fetched",
        )
    else:
        SystemLog.objects.create(
            level="WARNING",
            module="ingestion",
            message="Overpass refresh failed",
        )


def prune_ingestion_logs():
    """Delete RawIngestionLog entries older than 30 days."""
    from .models import RawIngestionLog

    cutoff = timezone.now() - timedelta(days=30)
    count, _ = RawIngestionLog.objects.filter(fetched_at__lt=cutoff).delete()
    logger.info("Pruned %d old ingestion logs", count)
    if count > 0:
        SystemLog.objects.create(
            level="INFO",
            module="ingestion",
            message=f"Pruned {count} ingestion logs older than 30 days",
        )
