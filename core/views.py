import json
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import Intersection, TrafficData
from features import classify_congestion
from prediction.models import Prediction


@login_required
def map_view(request):
    intersections = Intersection.objects.filter(is_active=True)
    # Use latest prediction date
    latest_pred = Prediction.objects.order_by("-target_date").first()
    tomorrow = latest_pred.target_date if latest_pred else date.today() + timedelta(days=1)
    preds = Prediction.objects.filter(target_date=tomorrow).select_related("intersection")

    markers = []
    for p in preds:
        ix = p.intersection
        cls = p.class_probabilities.get("predicted_class", "low") if p.class_probabilities else "low"
        markers.append({
            "id": ix.pk,
            "intersection_id": ix.intersection_id,
            "lat": ix.latitude,
            "lng": ix.longitude,
            "area": ix.area,
            "road": ix.road,
            "predicted_class": cls,
            "predicted_volume": p.predicted_volume or 0,
            "confidence": round(p.model_confidence, 2) if p.model_confidence else None,
            "recommended_green": p.recommended_signal_seconds,
            "target_date": str(p.target_date),
        })

    # Add intersections without predictions
    predicted_ids = {p.intersection_id for p in preds}
    for ix in intersections:
        if ix.pk not in predicted_ids:
            markers.append({
                "id": ix.pk,
                "intersection_id": ix.intersection_id,
                "lat": ix.latitude,
                "lng": ix.longitude,
                "area": ix.area,
                "road": ix.road,
                "predicted_class": "low",
                "predicted_volume": 0,
                "confidence": None,
                "recommended_green": ix.default_green_seconds,
                "target_date": str(tomorrow),
            })

    return render(request, "core/map.html", {
        "markers_json": json.dumps(markers),
        "tomorrow": tomorrow,
    })


@login_required
def intersection_list(request):
    intersections = Intersection.objects.filter(is_active=True)
    # Use latest prediction date
    latest_pred = Prediction.objects.order_by("-target_date").first()
    tomorrow = latest_pred.target_date if latest_pred else date.today() + timedelta(days=1)
    preds = {
        p.intersection_id: p
        for p in Prediction.objects.filter(target_date=tomorrow).select_related("intersection")
    }

    items = []
    for ix in intersections:
        pred = preds.get(ix.pk)
        cls = None
        if pred and pred.class_probabilities:
            cls = pred.class_probabilities.get("predicted_class")
        elif ix.hist_mean_congestion is not None:
            cls = classify_congestion(ix.hist_mean_congestion)
        items.append({"intersection": ix, "prediction": pred, "congestion_class": cls})

    return render(request, "core/intersection_list.html", {
        "items": items,
        "tomorrow": tomorrow,
    })


@login_required
def intersection_detail(request, pk):
    intersection = get_object_or_404(Intersection, pk=pk)
    tomorrow = date.today() + timedelta(days=1)

    # Latest prediction
    prediction = (
        Prediction.objects
        .filter(intersection=intersection)
        .order_by("-target_date")
        .first()
    )

    # Historical data for chart
    history = (
        TrafficData.objects
        .filter(intersection=intersection)
        .order_by("recorded_date")
        .values("recorded_date", "vehicle_count", "congestion_level")
    )
    hist_dates = [str(h["recorded_date"]) for h in history]
    hist_volume = [h["vehicle_count"] or 0 for h in history]
    hist_congestion = [h["congestion_level"] or 0 for h in history]

    # Recent records
    recent = TrafficData.objects.filter(intersection=intersection).order_by("-recorded_date")[:10]

    # Signal state
    try:
        signal_state = intersection.signal_state
    except Exception:
        signal_state = None

    context = {
        "intersection": intersection,
        "prediction": prediction,
        "signal_state": signal_state,
        "recent": recent,
        "hist_dates": json.dumps(hist_dates),
        "hist_volume": json.dumps(hist_volume),
        "hist_congestion": json.dumps(hist_congestion),
        "tomorrow": tomorrow,
    }
    return render(request, "core/intersection_detail.html", context)
