import json
import logging
import urllib.request
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from core.models import Intersection, SystemLog, TrafficData
from prediction.models import Prediction
from signals_app.models import EmergencyVehicle

logger = logging.getLogger("dashboard")


@login_required
def dashboard_view(request):
    intersections = Intersection.objects.filter(is_active=True)
    active_count = intersections.count()

    # Use latest prediction date (may differ from tomorrow if predictions are stale)
    latest_pred = Prediction.objects.order_by("-target_date").first()
    tomorrow = latest_pred.target_date if latest_pred else date.today() + timedelta(days=1)

    # Predictions for that date
    preds = Prediction.objects.filter(target_date=tomorrow)
    severe_count = preds.filter(
        class_probabilities__predicted_class__in=["severe", "high"]
    ).count()
    mean_volume = preds.aggregate(avg=Avg("predicted_volume"))["avg"] or 0

    # Open emergencies
    open_emergencies = EmergencyVehicle.objects.filter(route_cleared=False).count()

    # Attention list: high/severe predictions
    attention = (
        preds.filter(class_probabilities__predicted_class__in=["high", "severe"])
        .select_related("intersection")
        .order_by("-model_confidence")[:10]
    )

    # Volume trend chart — use latest data range (may be historical dataset)
    latest_td = TrafficData.objects.order_by("-recorded_date").first()
    if latest_td:
        end_date = latest_td.recorded_date
        start_date = end_date - timedelta(days=30)
    else:
        end_date = date.today()
        start_date = end_date - timedelta(days=30)
    daily_volume = (
        TrafficData.objects
        .filter(recorded_date__gte=start_date, recorded_date__lte=end_date)
        .values("recorded_date")
        .annotate(total=Avg("vehicle_count"))
        .order_by("recorded_date")
    )
    volume_labels = [str(d["recorded_date"]) for d in daily_volume]
    volume_data = [round(d["total"], 0) if d["total"] else 0 for d in daily_volume]

    # Congestion class distribution for tomorrow
    class_dist = {"low": 0, "moderate": 0, "high": 0, "severe": 0}
    for p in preds:
        cls = p.class_probabilities.get("predicted_class", "") if p.class_probabilities else ""
        if cls in class_dist:
            class_dist[cls] += 1

    # Recent logs
    recent_logs = SystemLog.objects.all()[:10]

    context = {
        "active_count": active_count,
        "severe_count": severe_count,
        "mean_volume": round(mean_volume),
        "open_emergencies": open_emergencies,
        "attention": attention,
        "volume_labels": json.dumps(volume_labels),
        "volume_data": json.dumps(volume_data),
        "class_dist": json.dumps(class_dist),
        "recent_logs": recent_logs,
        "tomorrow": tomorrow,
    }
    return render(request, "dashboard/home.html", context)


@login_required
def analytics_view(request):
    from prediction.registry import registry

    metrics = registry.metrics if registry.metrics else {}

    # Load leaderboard CSVs
    import csv
    from pathlib import Path
    from django.conf import settings

    meta_dir = Path(settings.ML_METADATA_DIR)

    reg_leaderboard = []
    cls_leaderboard = []

    reg_csv = meta_dir / "leaderboard_regression.csv"
    if reg_csv.exists():
        with open(reg_csv) as f:
            reg_leaderboard = list(csv.DictReader(f))

    cls_csv = meta_dir / "leaderboard_classification.csv"
    if cls_csv.exists():
        with open(cls_csv) as f:
            cls_leaderboard = list(csv.DictReader(f))

    # Feature importance from metrics
    feature_importance = []
    if metrics:
        test_data = metrics.get("test", {})
        reg_data = test_data.get("regression", {})
        best_reg = metrics.get("best_regressor", "RandomForest")
        best_reg_data = reg_data.get(best_reg, {})
        fi = best_reg_data.get("feature_importance", {})
        if fi:
            sorted_fi = sorted(fi.items(), key=lambda x: x[1], reverse=True)[:25]
            feature_importance = sorted_fi

    # Confusion matrix data
    confusion_data = None
    if metrics:
        test_cls = metrics.get("test", {}).get("classification", {})
        best_cls = metrics.get("best_classifier", "LightGBM")
        best_cls_data = test_cls.get(best_cls, {})
        cm = best_cls_data.get("confusion_matrix")
        if cm:
            confusion_data = json.dumps(cm)

    context = {
        "metrics": metrics,
        "reg_leaderboard": reg_leaderboard,
        "cls_leaderboard": cls_leaderboard,
        "feature_importance": json.dumps(feature_importance) if feature_importance else "[]",
        "confusion_data": confusion_data or "null",
        "best_classifier": metrics.get("best_classifier", "LightGBM"),
        "best_regressor": metrics.get("best_regressor", "RandomForest"),
    }
    # Intersection list for what-if form
    context["intersections"] = Intersection.objects.filter(is_active=True)
    return render(request, "dashboard/analytics.html", context)


@require_POST
@login_required
def whatif_predict_api(request):
    """AJAX endpoint: What-if congestion prediction given user inputs."""
    from prediction.registry import registry

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    vehicle_count = data.get("vehicle_count")
    hour = data.get("hour")
    weather = data.get("weather")
    intersection_id = data.get("intersection_id")

    if vehicle_count is None or weather is None:
        return JsonResponse({"error": "vehicle_count and weather are required"}, status=400)

    try:
        vehicle_count = int(vehicle_count)
        hour = int(hour) if hour is not None else 12
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid number format"}, status=400)

    # Clamp values
    vehicle_count = max(1000, min(80000, vehicle_count))
    hour = max(0, min(23, hour))

    # Optional specific intersection
    intersection = None
    if intersection_id:
        try:
            intersection = Intersection.objects.get(pk=intersection_id)
        except Intersection.DoesNotExist:
            pass

    try:
        result = registry.predict_whatif(vehicle_count, hour, weather, intersection)
        return JsonResponse(result)
    except Exception as e:
        logger.error("What-if prediction failed: %s", e)
        return JsonResponse({"error": str(e)}, status=500)


# WMO weather code to description mapping
_WMO_CODES = {
    0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime Fog", 51: "Light Drizzle", 53: "Moderate Drizzle",
    55: "Dense Drizzle", 61: "Slight Rain", 63: "Moderate Rain", 65: "Heavy Rain",
    71: "Slight Snow", 73: "Moderate Snow", 75: "Heavy Snow",
    80: "Slight Showers", 81: "Moderate Showers", 82: "Violent Showers",
    95: "Thunderstorm", 96: "Thunderstorm + Hail", 99: "Thunderstorm + Heavy Hail",
}

# WMO weather code to icon mapping
_WMO_ICONS = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️", 51: "🌦️", 53: "🌦️", 55: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️",
    71: "🌨️", 73: "🌨️", 75: "❄️",
    80: "🌦️", 81: "🌧️", 82: "⛈️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}


@login_required
def weather_api(request):
    """Proxy endpoint: fetch live weather for Bangalore from Open-Meteo (free, no key)."""
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        "latitude=12.9716&longitude=77.5946"
        "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
        "&timezone=Asia%2FKolkata"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "IntelliFlow/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        current = data.get("current", {})
        code = current.get("weather_code", 0)
        result = {
            "temperature": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "wind_speed": current.get("wind_speed_10m"),
            "weather_code": code,
            "condition": _WMO_CODES.get(code, "Unknown"),
            "icon": _WMO_ICONS.get(code, "🌡️"),
            "city": "Bangalore",
        }
        return JsonResponse(result)
    except Exception as e:
        logger.error("Weather API error: %s", e)
        return JsonResponse({"error": "Weather data unavailable"}, status=502)
