import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .ors_client import geocode, get_directions
from .route_scorer import score_route


@login_required
def route_planner(request):
    return render(request, "routing/planner.html")


@require_POST
def api_geocode(request):
    data = json.loads(request.body)
    query = data.get("query", "")
    results = geocode(query)
    return JsonResponse(results, safe=False)


@require_POST
def api_route(request):
    data = json.loads(request.body)
    start = data.get("start")  # [lng, lat]
    end = data.get("end")  # [lng, lat]

    if not start or not end:
        return JsonResponse({"error": "Missing start or end coordinates"}, status=400)

    routes = get_directions(tuple(start), tuple(end))
    if routes is None:
        return JsonResponse({
            "error": "Route service unavailable. Check ORS_API_KEY in .env.",
            "routes": [],
        }, status=503)

    scored_routes = []
    for i, route in enumerate(routes[:3]):
        summary = route.get("summary", {})
        geometry = route.get("geometry", "")

        # Decode polyline if needed (ORS returns encoded by default)
        coords = []
        if isinstance(geometry, str) and geometry:
            coords = decode_polyline(geometry)
        elif isinstance(geometry, dict):
            coords = geometry.get("coordinates", [])

        score_input = {
            "duration": summary.get("duration", 0),
            "distance": summary.get("distance", 0),
            "coordinates": coords,
        }
        scored = score_route(score_input)
        scored["route_index"] = i
        scored["geometry_coords"] = coords
        scored_routes.append(scored)

    # Sort by adjusted ETA
    scored_routes.sort(key=lambda r: r["adjusted_eta_seconds"])

    return JsonResponse({"routes": scored_routes})


def decode_polyline(encoded):
    """Decode a Google-style encoded polyline into [[lng, lat], ...]."""
    decoded = []
    index = 0
    lat = 0
    lng = 0

    while index < len(encoded):
        shift = 0
        result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        shift = 0
        result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng

        decoded.append([lng / 1e5, lat / 1e5])  # [lng, lat] for ORS

    return decoded
