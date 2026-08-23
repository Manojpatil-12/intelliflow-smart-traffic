import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from core.models import Intersection
from .models import DetectionEvent
from .yolo_service import is_available, detect_vehicles

logger = logging.getLogger("vision")


@login_required
def vision_upload(request):
    yolo_available = is_available()
    recent_events = DetectionEvent.objects.all()[:10]
    intersections = Intersection.objects.filter(is_active=True)

    return render(request, "vision/upload.html", {
        "yolo_available": yolo_available,
        "recent_events": recent_events,
        "intersections": intersections,
    })


@require_POST
@login_required
def vision_detect_api(request):
    """AJAX endpoint for vehicle detection."""
    if not is_available():
        return JsonResponse({"error": "YOLOv8 not available"}, status=503)

    image = request.FILES.get("image")
    if not image:
        return JsonResponse({"error": "No image provided"}, status=400)

    intersection_id = request.POST.get("intersection")

    # Save uploaded file
    event = DetectionEvent(image=image)
    if intersection_id:
        try:
            event.intersection = Intersection.objects.get(pk=intersection_id)
        except Intersection.DoesNotExist:
            pass
    event.save()

    # Run detection
    try:
        detection = detect_vehicles(event.image.path)
    except Exception as e:
        logger.error("Detection error: %s", e)
        return JsonResponse({"error": f"Detection failed: {str(e)}"}, status=500)

    if detection:
        event.counts = detection["counts"]
        event.total_vehicles = detection["total"]
        event.emergency_detected = detection["emergency_detected"]

        # Save annotated image
        from django.core.files import File
        from pathlib import Path
        annotated_path = detection["annotated_path"]
        if Path(annotated_path).exists():
            with open(annotated_path, "rb") as f:
                event.annotated_image.save(
                    f"annotated_{event.pk}.jpg", File(f), save=False
                )
        event.save()

        # Build annotated image URL
        annotated_url = None
        if event.annotated_image:
            annotated_url = event.annotated_image.url

        return JsonResponse({
            "success": True,
            "total": detection["total"],
            "counts": detection["counts"],
            "emergency_detected": detection["emergency_detected"],
            "annotated_url": annotated_url,
            "event_id": event.pk,
            "raw_count": len(detection.get("raw_detections", [])),
        })
    else:
        return JsonResponse({"error": "Detection returned no results"}, status=500)
