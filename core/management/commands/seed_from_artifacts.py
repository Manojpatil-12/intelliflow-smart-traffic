"""
Management command: seed_from_artifacts

Reads ML metadata and populates Intersection, TrafficData, and SignalState tables.
Idempotent — safe to re-run.
"""

import json
import csv
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Intersection, TrafficData
from signals_app.models import SignalState


class Command(BaseCommand):
    help = "Seed database from ML artifact metadata (intersections, history, signals)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush", action="store_true",
            help="Delete all seeded data before re-seeding.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview what would be seeded without writing to the database.",
        )

    def handle(self, *args, **options):
        flush = options["flush"]
        dry_run = options["dry_run"]
        meta_dir = Path(settings.ML_METADATA_DIR)

        intersections_path = meta_dir / "intersections.json"
        history_path = meta_dir / "history_tail.csv"

        if not intersections_path.exists():
            self.stderr.write(self.style.ERROR(f"Missing: {intersections_path}"))
            return
        if not history_path.exists():
            self.stderr.write(self.style.ERROR(f"Missing: {history_path}"))
            return

        # ── Flush ──
        if flush and not dry_run:
            self.stdout.write("Flushing seeded data...")
            TrafficData.objects.filter(source="dataset").delete()
            SignalState.objects.all().delete()
            Intersection.objects.all().delete()
            self.stdout.write(self.style.WARNING("Flushed."))

        # ── 1. Intersections ──
        with open(intersections_path) as f:
            intersections_data = json.load(f)

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"  Seeding {len(intersections_data)} intersections")
        self.stdout.write(f"{'='*60}")

        coord_warnings = []
        intersection_map = {}

        for item in intersections_data:
            iid = item["intersection_id"]
            if dry_run:
                self.stdout.write(f"  [DRY-RUN] Would create/update: {iid}")
                continue

            obj, created = Intersection.objects.update_or_create(
                intersection_id=iid,
                defaults={
                    "area": item["area"],
                    "road": item["road"],
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                    "coord_source": item.get("coord_source", "unknown"),
                    "num_approaches": item.get("num_approaches", 4),
                    "default_green_seconds": item.get("default_green_seconds", 45),
                    "hist_mean_volume": item.get("hist_mean_volume"),
                    "hist_mean_congestion": item.get("hist_mean_congestion"),
                    "hist_severe_rate": item.get("hist_severe_rate"),
                    "is_active": True,
                },
            )
            intersection_map[iid] = obj
            action = "Created" if created else "Updated"
            self.stdout.write(f"  {action}: {iid}")

            if item.get("coord_source") != "curated":
                coord_warnings.append(iid)

        if coord_warnings:
            self.stdout.write("")
            for w in coord_warnings:
                self.stdout.write(self.style.WARNING(
                    f"  ⚠ coord_source != 'curated': {w}"
                ))

        if dry_run:
            self.stdout.write(self.style.NOTICE("\nDry-run complete. No data written."))
            return

        # ── 2. TrafficData from history_tail.csv ──
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write("  Seeding TrafficData from history_tail.csv")
        self.stdout.write(f"{'='*60}")

        rows_created = 0
        rows_skipped = 0
        batch = []

        with open(history_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                iid = row["intersection_id"]
                intersection = intersection_map.get(iid)
                if not intersection:
                    self.stderr.write(f"  Unknown intersection: {iid}, skipping")
                    rows_skipped += 1
                    continue

                recorded = date.fromisoformat(row["date"])

                # Check for existing (idempotent)
                exists = TrafficData.objects.filter(
                    intersection=intersection, recorded_date=recorded
                ).exists()
                if exists:
                    rows_skipped += 1
                    continue

                def _float(val):
                    try:
                        v = float(val)
                        return v
                    except (ValueError, TypeError):
                        return None

                batch.append(TrafficData(
                    intersection=intersection,
                    recorded_date=recorded,
                    vehicle_count=_float(row.get("volume")),
                    avg_speed_kph=_float(row.get("speed")),
                    travel_time_index=_float(row.get("tti")),
                    congestion_level=_float(row.get("congestion")),
                    capacity_utilization=_float(row.get("capacity_util")),
                    incident_reports=_float(row.get("incidents")),
                    env_impact=_float(row.get("env_impact")),
                    pt_usage=_float(row.get("pt_usage")),
                    signal_compliance=_float(row.get("signal_compliance")),
                    parking_usage=_float(row.get("parking_usage")),
                    ped_count=_float(row.get("ped_count")),
                    weather_condition=row.get("weather", "Clear"),
                    roadwork=row.get("roadwork", "No"),
                    source="dataset",
                    is_synthetic=row.get("is_synthetic", "0") in ("1", "True", "true"),
                ))

                if len(batch) >= 500:
                    TrafficData.objects.bulk_create(batch, ignore_conflicts=True)
                    rows_created += len(batch)
                    batch = []

        if batch:
            TrafficData.objects.bulk_create(batch, ignore_conflicts=True)
            rows_created += len(batch)

        self.stdout.write(f"  Created: {rows_created} rows")
        self.stdout.write(f"  Skipped (existing): {rows_skipped} rows")

        # ── 3. SignalState per intersection ──
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write("  Creating SignalState per intersection")
        self.stdout.write(f"{'='*60}")

        signals_created = 0
        for intersection in Intersection.objects.all():
            _, created = SignalState.objects.get_or_create(
                intersection=intersection,
                defaults={
                    "current_state": "green",
                    "green_duration_seconds": intersection.default_green_seconds,
                },
            )
            if created:
                signals_created += 1
        self.stdout.write(f"  Signal states created: {signals_created}")

        # ── Summary ──
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write("  SEED SUMMARY")
        self.stdout.write(f"{'='*60}")

        from django.db.models import Count, Min, Max
        stats = (
            TrafficData.objects
            .filter(source="dataset")
            .values("intersection__intersection_id")
            .annotate(
                count=Count("id"),
                min_date=Min("recorded_date"),
                max_date=Max("recorded_date"),
            )
            .order_by("intersection__intersection_id")
        )

        self.stdout.write(f"\n  {'Intersection':<45} {'Days':>5}  {'From':>12}  {'To':>12}")
        self.stdout.write(f"  {'-'*45} {'-'*5}  {'-'*12}  {'-'*12}")

        min_depth = float("inf")
        for s in stats:
            iid = s["intersection__intersection_id"]
            cnt = s["count"]
            min_depth = min(min_depth, cnt)
            self.stdout.write(
                f"  {iid:<45} {cnt:>5}  {s['min_date']}  {s['max_date']}"
            )

        self.stdout.write(f"\n  Min history depth: {min_depth} days")
        from features import MIN_HISTORY_DAYS
        if min_depth >= MIN_HISTORY_DAYS:
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ All intersections meet MIN_HISTORY_DAYS ({MIN_HISTORY_DAYS})"
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"  ✗ Some intersections below MIN_HISTORY_DAYS ({MIN_HISTORY_DAYS})!"
            ))
