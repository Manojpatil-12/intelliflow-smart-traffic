"""Pre-deployment check: verifies artifacts, models, and feature contract."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Verify deployment readiness: artifacts, models, feature contract."

    def handle(self, *args, **options):
        ok = True

        # 1. Check artifact directories exist
        for label, path in [
            ("ML dir", settings.ML_DIR),
            ("Models dir", settings.ML_MODELS_DIR),
            ("Encoders dir", settings.ML_ENCODERS_DIR),
            ("Metadata dir", settings.ML_METADATA_DIR),
        ]:
            p = Path(path)
            if p.exists():
                self.stdout.write(self.style.SUCCESS(f"  ✓ {label}: {p}"))
            else:
                self.stdout.write(self.style.ERROR(f"  ✗ {label} missing: {p}"))
                ok = False

        # 2. Check key files
        key_files = [
            settings.ML_MODELS_DIR / "BEST_classifier.pkl",
            settings.ML_MODELS_DIR / "BEST_regressor.pkl",
            settings.ML_ENCODERS_DIR / "encoders_full.pkl",
            settings.ML_METADATA_DIR / "feature_columns.json",
            settings.ML_METADATA_DIR / "intersections.json",
            settings.ML_METADATA_DIR / "metrics.json",
        ]
        for f in key_files:
            p = Path(f)
            if p.exists():
                self.stdout.write(self.style.SUCCESS(f"  ✓ {p.name}"))
            else:
                self.stdout.write(self.style.ERROR(f"  ✗ Missing: {p}"))
                ok = False

        # 3. Check registry loads
        from prediction.registry import registry
        if not registry._loaded:
            registry.load()

        if registry.is_healthy():
            self.stdout.write(self.style.SUCCESS("  ✓ Model registry healthy"))
        else:
            self.stdout.write(self.style.ERROR(
                f"  ✗ Registry unhealthy: {registry.load_errors}"
            ))
            ok = False

        # 4. Feature contract
        if registry.feature_columns:
            import json
            with open(settings.ML_METADATA_DIR / "feature_columns.json") as f:
                expected = json.load(f)
            if registry.feature_columns == expected:
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ Feature contract: {len(expected)} columns match"
                ))
            else:
                self.stdout.write(self.style.ERROR("  ✗ Feature columns mismatch!"))
                ok = False

        # 5. Database check
        from core.models import Intersection, TrafficData
        ix_count = Intersection.objects.count()
        td_count = TrafficData.objects.count()
        self.stdout.write(f"  Intersections: {ix_count}, TrafficData rows: {td_count}")
        if ix_count == 0:
            self.stdout.write(self.style.WARNING("  ⚠ No intersections. Run seed_from_artifacts."))

        # Summary
        self.stdout.write("")
        if ok:
            self.stdout.write(self.style.SUCCESS("  ✓ DEPLOYMENT CHECK PASSED"))
        else:
            self.stdout.write(self.style.ERROR("  ✗ DEPLOYMENT CHECK FAILED"))
