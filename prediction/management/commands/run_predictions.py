"""
Management command: run_predictions

Runs predict() for every active intersection, prints a result table.
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from core.models import Intersection
from prediction.registry import registry, InsufficientHistoryError


class Command(BaseCommand):
    help = "Run predictions for all active intersections."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date", type=str, default=None,
            help="Target date (YYYY-MM-DD). Defaults to tomorrow.",
        )

    def handle(self, *args, **options):
        target = options["date"]
        if target:
            target_date = date.fromisoformat(target)
        else:
            target_date = date.today() + timedelta(days=1)

        if not registry.is_healthy():
            self.stderr.write(self.style.ERROR(
                f"Registry not healthy: {registry.load_errors}"
            ))
            return

        intersections = Intersection.objects.filter(is_active=True)
        self.stdout.write(f"\nRunning predictions for {target_date} "
                          f"({intersections.count()} intersections)\n")

        results = []
        errors = []

        for ix in intersections:
            try:
                payload = registry.predict(ix, target_date)
                results.append(payload)
            except InsufficientHistoryError as e:
                errors.append((ix.intersection_id, str(e)))
            except Exception as e:
                errors.append((ix.intersection_id, str(e)))

        # Print results table
        if results:
            self.stdout.write(
                f"  {'Intersection':<45} {'Class':<10} {'Volume':>10} "
                f"{'Green':>6} {'Conf':>6}"
            )
            self.stdout.write(
                f"  {'-'*45} {'-'*10} {'-'*10} {'-'*6} {'-'*6}"
            )
            for r in results:
                conf = f"{r['confidence']:.2f}" if r['confidence'] else "N/A"
                self.stdout.write(
                    f"  {r['intersection_id']:<45} {r['predicted_class']:<10} "
                    f"{r['predicted_volume']:>10.0f} {r['recommended_green_seconds']:>5}s "
                    f"{conf:>6}"
                )

        if errors:
            self.stdout.write(self.style.WARNING(f"\n  Errors ({len(errors)}):"))
            for iid, msg in errors:
                self.stdout.write(f"    {iid}: {msg}")

        # Summary
        self.stdout.write(f"\n  Predictions: {len(results)} OK, {len(errors)} errors")

        if results:
            classes = [r["predicted_class"] for r in results]
            from collections import Counter
            dist = Counter(classes)
            self.stdout.write(f"  Class distribution: {dict(dist)}")
