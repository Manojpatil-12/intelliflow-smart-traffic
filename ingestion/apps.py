import os
import logging

from django.apps import AppConfig

logger = logging.getLogger("ingestion")


class IngestionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ingestion"

    def ready(self):
        # Guard against autoreload double-start
        if os.environ.get("RUN_MAIN") != "true":
            return

        # Skip scheduler during `runserver` (use Daphne for production)
        import sys
        if "runserver" in sys.argv:
            logger.info("Skipping scheduler in runserver mode.")
            return

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from django_apscheduler.jobstores import DjangoJobStore

            scheduler = BackgroundScheduler()
            scheduler.add_jobstore(DjangoJobStore(), "default")

            from .jobs import (
                ingest_traffic,
                ingest_weather,
                run_daily_predictions,
                refresh_overpass,
                prune_ingestion_logs,
            )

            scheduler.add_job(
                ingest_traffic,
                "interval", minutes=5,
                id="ingest_traffic",
                replace_existing=True,
            )
            scheduler.add_job(
                ingest_weather,
                "interval", minutes=5,
                id="ingest_weather",
                replace_existing=True,
            )
            scheduler.add_job(
                run_daily_predictions,
                "cron", hour=2, minute=0,
                id="daily_predictions",
                replace_existing=True,
            )
            scheduler.add_job(
                refresh_overpass,
                "cron", day_of_week="mon", hour=4, minute=0,
                id="overpass_refresh",
                replace_existing=True,
            )
            scheduler.add_job(
                prune_ingestion_logs,
                "cron", hour=3, minute=0,
                id="prune_logs",
                replace_existing=True,
            )

            scheduler.start()
            logger.info("APScheduler started with 5 jobs.")
        except Exception as e:
            logger.error("Failed to start scheduler: %s", e)
