"""
ModelRegistry — module-level singleton, loaded once at app ready.
Loads ML models, encoders, and metadata. Falls back gracefully.
"""

import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from django.conf import settings

logger = logging.getLogger("prediction.registry")


class FeatureContractError(Exception):
    """Raised when inference row columns don't match the trained feature set."""
    pass


class InsufficientHistoryError(Exception):
    """Raised when an intersection has fewer rows than MIN_HISTORY_DAYS."""
    pass


class ModelRegistry:
    def __init__(self):
        self.classifier = None
        self.regressor = None
        self.encoders = None
        self.scaler = None
        self.label_encoders = None
        self.feature_columns = None
        self.config = None
        self.metrics = None
        self.load_errors = []
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        self._loaded = True

        models_dir = Path(settings.ML_MODELS_DIR)
        encoders_dir = Path(settings.ML_ENCODERS_DIR)
        metadata_dir = Path(settings.ML_METADATA_DIR)

        # ── Feature columns (required) ──
        try:
            with open(metadata_dir / "feature_columns.json") as f:
                self.feature_columns = json.load(f)
        except Exception as e:
            self.load_errors.append(f"feature_columns.json: {e}")
            logger.error("Failed to load feature_columns.json: %s", e)

        # ── Config ──
        try:
            with open(metadata_dir / "feature_config.json") as f:
                self.config = json.load(f)
        except Exception as e:
            self.load_errors.append(f"feature_config.json: {e}")
            logger.warning("Failed to load feature_config.json: %s", e)

        # ── Metrics ──
        try:
            with open(metadata_dir / "metrics.json") as f:
                self.metrics = json.load(f)
        except Exception as e:
            self.load_errors.append(f"metrics.json: {e}")
            logger.warning("Failed to load metrics.json: %s", e)

        # ── Encoders ──
        try:
            self.encoders = joblib.load(encoders_dir / "encoders_full.pkl")
        except Exception as e:
            self.load_errors.append(f"encoders_full.pkl: {e}")
            logger.error("Failed to load encoders: %s", e)

        try:
            self.scaler = joblib.load(encoders_dir / "scaler.pkl")
        except Exception as e:
            self.load_errors.append(f"scaler.pkl: {e}")
            logger.warning("Failed to load scaler: %s", e)

        try:
            self.label_encoders = joblib.load(encoders_dir / "label_encoders.pkl")
        except Exception as e:
            self.load_errors.append(f"label_encoders.pkl: {e}")
            logger.warning("Failed to load label_encoders: %s", e)

        # ── Classifier: try BEST first, then fallbacks ──
        self.classifier = self._load_model(
            models_dir, "BEST_classifier.pkl",
            fallback_prefix="cls_", label="classifier"
        )

        # ── Regressor: try BEST first, then fallbacks ──
        self.regressor = self._load_model(
            models_dir, "BEST_regressor.pkl",
            fallback_prefix="reg_", label="regressor"
        )

        if self.load_errors:
            logger.warning("Registry loaded with %d errors: %s",
                           len(self.load_errors), self.load_errors)
        else:
            logger.info("Registry loaded successfully.")

    def _load_model(self, models_dir, best_name, fallback_prefix, label):
        best_path = models_dir / best_name
        try:
            model = joblib.load(best_path)
            logger.info("Loaded %s from %s", label, best_name)
            return model
        except Exception as e:
            self.load_errors.append(f"{best_name}: {e}")
            logger.warning("Failed to load %s, trying fallbacks: %s", best_name, e)

        # Try fallbacks
        fallbacks = sorted(models_dir.glob(f"{fallback_prefix}*.pkl"))
        for fb_path in fallbacks:
            try:
                model = joblib.load(fb_path)
                logger.info("Loaded %s fallback from %s", label, fb_path.name)
                return model
            except Exception as e:
                self.load_errors.append(f"{fb_path.name}: {e}")
                logger.warning("Fallback %s failed: %s", fb_path.name, e)

        logger.error("No %s model could be loaded!", label)
        return None

    def is_healthy(self):
        return (
            self.classifier is not None
            and self.regressor is not None
            and self.encoders is not None
            and self.feature_columns is not None
        )

    def predict(self, intersection, target_date, weather_forecast=None,
                roadwork_planned=False):
        """
        Run prediction for a single intersection and target_date.
        Returns a dict with all prediction data.
        """
        from features import (
            build_inference_row, classify_congestion,
            recommend_green_seconds, FEATURE_VERSION, MIN_HISTORY_DAYS,
        )
        from core.models import TrafficData

        if not self.is_healthy():
            raise RuntimeError("Model registry is not healthy: " + str(self.load_errors))

        # a. Pull history for this intersection
        history_qs = (
            TrafficData.objects
            .filter(intersection=intersection)
            .order_by("recorded_date")
        )
        history_df = self._qs_to_raw_df(history_qs)

        if len(history_df) < MIN_HISTORY_DAYS:
            raise InsufficientHistoryError(
                f"Need >= {MIN_HISTORY_DAYS} days for {intersection.intersection_id}, "
                f"got {len(history_df)}"
            )

        # b. Pull peer rows for neighbour features
        peer_qs = (
            TrafficData.objects
            .filter(intersection__area=intersection.area)
            .exclude(intersection=intersection)
            .order_by("recorded_date")
        )
        peer_df = self._qs_to_raw_df(peer_qs) if peer_qs.exists() else None

        # Weather default
        if not weather_forecast:
            from core.models import Weather
            latest_weather = Weather.objects.first()
            if latest_weather and latest_weather.condition:
                weather_forecast = latest_weather.condition
                weather_assumed = False
            else:
                weather_forecast = "Clear"
                weather_assumed = True
        else:
            weather_assumed = False

        # c. Build inference row
        row = build_inference_row(
            history_df=history_df,
            target_date=target_date,
            area=intersection.area,
            road=intersection.road,
            weather_forecast=weather_forecast,
            roadwork_planned=roadwork_planned,
            encoders=self.encoders,
            peer_history=peer_df,
        )

        # d. Assert feature contract
        expected_cols = self.feature_columns
        actual_cols = list(row.columns)
        if actual_cols != expected_cols:
            missing = set(expected_cols) - set(actual_cols)
            extra = set(actual_cols) - set(expected_cols)
            diff_msg = f"Missing: {missing}, Extra: {extra}"
            logger.error("Feature contract mismatch: %s", diff_msg)
            raise FeatureContractError(diff_msg)

        # e. Run predictions
        X = row[expected_cols]

        # Classifier
        cls_pred = self.classifier.predict(X)[0]
        cls_proba = {}
        if hasattr(self.classifier, "predict_proba"):
            probas = self.classifier.predict_proba(X)[0]
            classes = self.classifier.classes_
            cls_proba = {str(c): round(float(p), 4) for c, p in zip(classes, probas)}

        # Decode class label
        if self.label_encoders and "congestion_class" in self.label_encoders:
            le = self.label_encoders["congestion_class"]
            predicted_class = le.inverse_transform([int(cls_pred)])[0]
        else:
            predicted_class = classify_congestion(float(cls_pred) * 25)

        # Regressor
        reg_pred = float(self.regressor.predict(X)[0])

        # Confidence (max probability)
        confidence = max(cls_proba.values()) if cls_proba else None

        # Recommended green
        rec_green = recommend_green_seconds(
            predicted_class, intersection.num_approaches
        )

        # Build payload
        payload = {
            "intersection_id": intersection.intersection_id,
            "target_date": str(target_date),
            "predicted_class": predicted_class,
            "predicted_volume": round(reg_pred, 1),
            "class_probabilities": cls_proba,
            "confidence": confidence,
            "recommended_green_seconds": rec_green,
            "weather_forecast": weather_forecast,
            "weather_assumed": weather_assumed,
            "roadwork_planned": roadwork_planned,
            "feature_version": FEATURE_VERSION,
            "model_classifier": type(self.classifier).__name__,
            "model_regressor": type(self.regressor).__name__,
        }

        # Derive numeric congestion from class
        class_to_level = {"low": 20, "moderate": 52, "high": 75, "severe": 92}
        congestion_level = class_to_level.get(predicted_class, 50)

        # f. Persist prediction
        from prediction.models import Prediction
        pred_obj, _ = Prediction.objects.update_or_create(
            intersection=intersection,
            target_date=target_date,
            model_used=f"{type(self.classifier).__name__}+{type(self.regressor).__name__}",
            defaults={
                "predicted_volume": round(reg_pred, 1),
                "congestion_level": congestion_level,
                "class_probabilities": {
                    "predicted_class": predicted_class,
                    "probabilities": cls_proba,
                },
                "recommended_signal_seconds": rec_green,
                "model_confidence": confidence,
                "feature_version": FEATURE_VERSION,
                "input_payload": payload,
            },
        )

        payload["prediction_id"] = pred_obj.pk
        return payload

    def predict_whatif(self, vehicle_count, hour_of_day, weather, intersection=None):
        """
        What-if prediction: given user-provided inputs (vehicle count, time, weather),
        use a real intersection's history to build features and override key values.
        Returns predicted class, volume, green time, and probabilities.
        """
        from features import (
            build_inference_row, recommend_green_seconds, MIN_HISTORY_DAYS,
        )
        from core.models import Intersection, TrafficData
        from datetime import date, timedelta
        import math

        if not self.is_healthy():
            raise RuntimeError("Model registry is not healthy")

        # Pick an intersection (use one with most data, or user-specified)
        if intersection is None:
            from django.db.models import Count
            intersection = (
                Intersection.objects
                .annotate(td_count=Count("traffic_data"))
                .filter(td_count__gte=MIN_HISTORY_DAYS)
                .order_by("-td_count")
                .first()
            )
        if not intersection:
            raise RuntimeError("No intersection with enough history")

        # Get history
        history_qs = TrafficData.objects.filter(intersection=intersection).order_by("recorded_date")
        history_df = self._qs_to_raw_df(history_qs)

        # Get peer data
        peer_qs = (
            TrafficData.objects
            .filter(intersection__area=intersection.area)
            .exclude(intersection=intersection)
            .order_by("recorded_date")
        )
        peer_df = self._qs_to_raw_df(peer_qs) if peer_qs.exists() else None

        # Use the latest date + 1 as target
        latest_date = history_df["Date"].max()
        target_date = latest_date + timedelta(days=1)

        # Build the inference row using real history
        row = build_inference_row(
            history_df=history_df,
            target_date=target_date.date() if hasattr(target_date, 'date') else target_date,
            area=intersection.area,
            road=intersection.road,
            weather_forecast=weather,
            roadwork_planned=False,
            encoders=self.encoders,
            peer_history=peer_df,
        )

        # Override features based on user inputs
        expected_cols = self.feature_columns

        # Scale volume-related features proportionally
        if "volume_lag_1" in row.columns and row["volume_lag_1"].values[0] > 0:
            ratio = vehicle_count / row["volume_lag_1"].values[0]
        else:
            ratio = 1.0

        vol_cols = [c for c in row.columns if "volume" in c.lower() and c in expected_cols]
        for vc in vol_cols:
            row[vc] = row[vc] * ratio

        # Override temporal features based on hour_of_day
        dow = target_date.weekday() if hasattr(target_date, 'weekday') else 0
        # Map hour to approximate day characteristics
        if "is_weekend" in row.columns:
            row["is_weekend"] = 1 if dow >= 5 else 0
        if "day_of_week" in row.columns:
            row["day_of_week"] = dow
        if "dow_sin" in row.columns:
            row["dow_sin"] = math.sin(2 * math.pi * dow / 7)
        if "dow_cos" in row.columns:
            row["dow_cos"] = math.cos(2 * math.pi * dow / 7)

        # Ensure correct columns
        X = row[expected_cols]

        # Run classifier
        cls_pred = self.classifier.predict(X)[0]
        cls_proba = {}
        if hasattr(self.classifier, "predict_proba"):
            probas = self.classifier.predict_proba(X)[0]
            classes = self.classifier.classes_
            cls_proba = {str(c): round(float(p), 4) for c, p in zip(classes, probas)}

        # Decode class label
        if self.label_encoders and "congestion_class" in self.label_encoders:
            le = self.label_encoders["congestion_class"]
            predicted_class = le.inverse_transform([int(cls_pred)])[0]
        else:
            from features import classify_congestion
            predicted_class = classify_congestion(float(cls_pred) * 25)

        # Run regressor
        reg_pred = float(self.regressor.predict(X)[0])

        # Recommended green time
        rec_green = recommend_green_seconds(predicted_class)

        # Congestion level
        class_to_level = {"low": 20, "moderate": 52, "high": 75, "severe": 92}
        congestion_level = class_to_level.get(predicted_class, 50)

        return {
            "predicted_class": predicted_class,
            "predicted_volume": round(reg_pred),
            "congestion_level": congestion_level,
            "recommended_green_seconds": rec_green,
            "class_probabilities": cls_proba,
            "confidence": max(cls_proba.values()) if cls_proba else None,
            "input_vehicles": vehicle_count,
            "input_weather": weather,
            "input_hour": hour_of_day,
            "intersection_used": intersection.intersection_id,
        }

    @staticmethod
    def _qs_to_raw_df(qs):
        """Convert a TrafficData QuerySet to the raw-schema DataFrame features.py expects."""
        rows = list(qs.values(
            "intersection__intersection_id", "intersection__area", "intersection__road",
            "recorded_date", "vehicle_count", "avg_speed_kph", "travel_time_index",
            "congestion_level", "capacity_utilization", "incident_reports",
            "env_impact", "pt_usage", "signal_compliance", "parking_usage",
            "ped_count", "weather_condition", "roadwork", "is_synthetic",
        ))
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df.rename(columns={
            "recorded_date": "Date",
            "intersection__area": "Area Name",
            "intersection__road": "Road/Intersection Name",
            "vehicle_count": "Traffic Volume",
            "avg_speed_kph": "Average Speed",
            "travel_time_index": "Travel Time Index",
            "congestion_level": "Congestion Level",
            "capacity_utilization": "Road Capacity Utilization",
            "incident_reports": "Incident Reports",
            "env_impact": "Environmental Impact",
            "pt_usage": "Public Transport Usage",
            "signal_compliance": "Traffic Signal Compliance",
            "parking_usage": "Parking Usage",
            "ped_count": "Pedestrian and Cyclist Count",
            "weather_condition": "Weather Conditions",
            "roadwork": "Roadwork and Construction Activity",
        })
        df["Date"] = pd.to_datetime(df["Date"])
        # Fill nulls for roadwork
        df["Roadwork and Construction Activity"] = (
            df["Roadwork and Construction Activity"].fillna("No")
        )
        return df


# ── Module-level singleton ──
registry = ModelRegistry()
