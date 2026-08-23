from datetime import date, timedelta

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import Intersection
from prediction.models import Prediction


@require_GET
def latest_predictions(request):
    latest_pred = Prediction.objects.order_by("-target_date").first()
    target = latest_pred.target_date if latest_pred else date.today() + timedelta(days=1)
    preds = Prediction.objects.filter(target_date=target).select_related("intersection")
    data = []
    for p in preds:
        ix = p.intersection
        cls = p.class_probabilities.get("predicted_class", "low") if p.class_probabilities else "low"
        data.append({
            "intersection_id": ix.intersection_id,
            "lat": ix.latitude,
            "lng": ix.longitude,
            "predicted_class": cls,
            "predicted_volume": p.predicted_volume,
            "confidence": round(p.model_confidence, 2) if p.model_confidence else None,
            "recommended_green": p.recommended_signal_seconds,
            "target_date": str(p.target_date),
        })
    return JsonResponse(data, safe=False)


@require_GET
def intersection_list_api(request):
    intersections = Intersection.objects.filter(is_active=True)
    data = [{
        "id": ix.pk,
        "intersection_id": ix.intersection_id,
        "area": ix.area,
        "road": ix.road,
        "lat": ix.latitude,
        "lng": ix.longitude,
    } for ix in intersections]
    return JsonResponse(data, safe=False)
