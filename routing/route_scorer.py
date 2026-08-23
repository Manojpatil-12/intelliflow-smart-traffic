"""Score routes using predicted congestion from nearby intersections."""

import logging
from datetime import date, timedelta

from core.models import Intersection
from prediction.models import Prediction
from routing.ors_client import haversine_distance

logger = logging.getLogger("routing.scorer")

PENALTY = {"low": 1.0, "moderate": 1.15, "high": 1.4, "severe": 1.8}
PROXIMITY_M = 500


def score_route(route_geometry, target_date=None):
    """
    Given an ORS route geometry (decoded coordinates), find intersections
    within 500m and apply congestion penalty.

    Returns dict with:
        base_eta, adjusted_eta, penalty_factor, congested_intersections
    """
    if target_date is None:
        latest = Prediction.objects.order_by("-target_date").values_list("target_date", flat=True).first()
        target_date = latest if latest else date.today() + timedelta(days=1)

    base_duration = route_geometry.get("duration", 0)  # seconds
    base_distance = route_geometry.get("distance", 0)  # meters

    # Get predictions keyed by intersection
    intersections = Intersection.objects.filter(is_active=True)
    preds = {
        p.intersection_id: p
        for p in Prediction.objects.filter(target_date=target_date)
    }

    # Decode coordinates from the route
    coords = route_geometry.get("coordinates", [])
    if not coords:
        return {
            "base_eta_seconds": base_duration,
            "adjusted_eta_seconds": base_duration,
            "base_distance_m": base_distance,
            "penalty_factor": 1.0,
            "congested_intersections": [],
        }

    # Find intersections near the route
    congested = []
    seen = set()
    sample_step = max(1, len(coords) // 50)  # Sample points along route

    for i in range(0, len(coords), sample_step):
        point = coords[i]
        # ORS coordinates are [lng, lat]
        route_lat, route_lng = point[1], point[0]

        for ix in intersections:
            if ix.pk in seen:
                continue
            dist = haversine_distance(route_lat, route_lng, ix.latitude, ix.longitude)
            if dist <= PROXIMITY_M:
                seen.add(ix.pk)
                pred = preds.get(ix.pk)
                cls = "low"
                if pred and pred.class_probabilities:
                    cls = pred.class_probabilities.get("predicted_class", "low")
                penalty = PENALTY.get(cls, 1.0)
                if penalty > 1.0:
                    congested.append({
                        "intersection_id": ix.intersection_id,
                        "area": ix.area,
                        "road": ix.road,
                        "predicted_class": cls,
                        "penalty": penalty,
                        "distance_m": round(dist),
                    })

    # Calculate adjusted ETA
    total_penalty = 1.0
    for c in congested:
        total_penalty *= c["penalty"]

    # Average penalty across route (geometric mean approach)
    if congested:
        avg_penalty = total_penalty ** (1 / len(congested))
        # Scale adjustment based on how many congested intersections vs total
        adjustment = 1.0 + (avg_penalty - 1.0) * min(len(congested) / 5, 1.0)
    else:
        adjustment = 1.0

    adjusted_duration = base_duration * adjustment

    return {
        "base_eta_seconds": round(base_duration),
        "adjusted_eta_seconds": round(adjusted_duration),
        "base_distance_m": round(base_distance),
        "penalty_factor": round(adjustment, 3),
        "congested_intersections": congested,
    }
