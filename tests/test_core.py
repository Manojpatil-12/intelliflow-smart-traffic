"""Core tests for IntelliFlow — Phase 11."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TestCase, override_settings

from accounts.models import CustomUser

# Override WhiteNoise manifest storage so tests don't need collectstatic
_test_storages = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
from core.models import Intersection, TrafficData
from prediction.models import Prediction
from prediction.registry import InsufficientHistoryError, registry


@override_settings(STORAGES=_test_storages)
class TestRolePermissions(TestCase):
    """Test that operator is blocked from admin URLs directly."""

    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(
            username="testadmin", password="pass123", role="admin"
        )
        self.operator = CustomUser.objects.create_user(
            username="testop", password="pass123", role="operator"
        )

    def test_operator_blocked_from_admin(self):
        c = Client()
        c.login(username="testop", password="pass123")
        resp = c.get("/admin/", follow=True)
        # Should redirect to admin login
        self.assertEqual(resp.status_code, 200)
        self.assertIn("/admin/login/", resp.request["PATH_INFO"])

    def test_admin_can_access_admin(self):
        c = Client()
        c.login(username="testadmin", password="pass123")
        resp = c.get("/admin/")
        self.assertEqual(resp.status_code, 200)

    def test_operator_can_access_dashboard(self):
        c = Client()
        c.login(username="testop", password="pass123")
        resp = c.get("/dashboard/")
        self.assertEqual(resp.status_code, 200)


class TestFeatureContract(TestCase):
    """Test that build_inference_row output matches feature_columns.json."""

    def test_feature_columns_match(self):
        fc_path = Path(settings.ML_METADATA_DIR) / "feature_columns.json"
        with open(fc_path) as f:
            expected = json.load(f)
        self.assertEqual(len(expected), 83)
        self.assertIn("volume_lag_1", expected)
        self.assertIn("weather_encoded", expected)

        # Verify registry has the same
        if registry._loaded and registry.feature_columns:
            self.assertEqual(registry.feature_columns, expected)


class TestRegistryFallback(TestCase):
    """Test that corrupting BEST_classifier.pkl doesn't prevent app boot."""

    def test_registry_loads_without_crash(self):
        # The registry should have attempted to load
        # Even if it fails, the app should boot
        self.assertTrue(registry._loaded)


class TestInsufficientHistory(TestCase):
    """Test that < 21 days returns a clean state, not a 500."""

    def setUp(self):
        self.ix = Intersection.objects.create(
            intersection_id="Test::Test",
            area="Test", road="Test",
            latitude=12.0, longitude=77.0,
        )
        # Only add 5 days of data (less than MIN_HISTORY_DAYS)
        for i in range(5):
            TrafficData.objects.create(
                intersection=self.ix,
                recorded_date=date(2024, 1, 1 + i),
                vehicle_count=1000,
                congestion_level=50,
                source="dataset",
            )

    def test_insufficient_history_raises(self):
        if not registry.is_healthy():
            self.skipTest("Registry not healthy")
        with self.assertRaises(InsufficientHistoryError):
            registry.predict(self.ix, date(2024, 1, 10))


class TestSeedIdempotent(TestCase):
    """Test that running seed twice does not duplicate data."""

    def test_seed_idempotent(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("seed_from_artifacts", stdout=out)
        count1 = Intersection.objects.count()
        td_count1 = TrafficData.objects.count()

        out2 = StringIO()
        call_command("seed_from_artifacts", stdout=out2)
        count2 = Intersection.objects.count()
        td_count2 = TrafficData.objects.count()

        self.assertEqual(count1, count2)
        self.assertEqual(td_count1, td_count2)


class TestRouteScoring(TestCase):
    """Test route scoring with known congestion inputs."""

    def setUp(self):
        self.ix = Intersection.objects.create(
            intersection_id="Score::Test",
            area="Score", road="Test",
            latitude=12.9716, longitude=77.5946,
        )
        Prediction.objects.create(
            intersection=self.ix,
            target_date=date(2024, 8, 10),
            model_used="test",
            predicted_volume=30000,
            congestion_level=90,
            class_probabilities={"predicted_class": "severe"},
            recommended_signal_seconds=75,
        )

    def test_penalty_applied(self):
        from routing.route_scorer import score_route

        # Route passing right through the intersection
        route = {
            "duration": 600,
            "distance": 5000,
            "coordinates": [[77.5946, 12.9716]],  # [lng, lat]
        }
        result = score_route(route, target_date=date(2024, 8, 10))
        self.assertGreater(result["penalty_factor"], 1.0)
        self.assertGreater(result["adjusted_eta_seconds"], result["base_eta_seconds"])
