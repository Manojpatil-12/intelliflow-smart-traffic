"""OpenRouteService client for geocoding and directions."""

import logging
import math

import requests
from django.conf import settings

logger = logging.getLogger("routing.ors")

ORS_BASE = "https://api.openrouteservice.org"
NOMINATIM_BASE = "https://nominatim.openstreetmap.org"


def geocode(query, limit=5):
    """Geocode a query using Nominatim (no API key needed)."""
    try:
        resp = requests.get(
            f"{NOMINATIM_BASE}/search",
            params={"q": query, "format": "json", "limit": limit, "countrycodes": "in"},
            headers={"User-Agent": "IntelliFlow/1.0 (traffic-prediction)"},
            timeout=5,
        )
        resp.raise_for_status()
        results = resp.json()
        return [
            {
                "display_name": r["display_name"],
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
            }
            for r in results
        ]
    except Exception as e:
        logger.error("Geocode failed: %s", e)
        return []


def get_directions(start_coords, end_coords):
    """
    Get directions from ORS.
    start_coords/end_coords: (lng, lat) tuples.
    Returns list of route dicts or None on failure.
    """
    api_key = settings.ORS_API_KEY
    if not api_key:
        logger.warning("ORS_API_KEY not set, directions unavailable")
        return None

    try:
        resp = requests.post(
            f"{ORS_BASE}/v2/directions/driving-car",
            json={
                "coordinates": [list(start_coords), list(end_coords)],
                "alternative_routes": {"target_count": 3, "weight_factor": 1.6},
                "geometry": True,
            },
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        routes = data.get("routes", [])
        return routes
    except Exception as e:
        logger.error("ORS directions failed: %s", e)
        return None


def haversine_distance(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters between two points."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
