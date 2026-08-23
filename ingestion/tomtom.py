"""TomTom Traffic Flow API adapter."""

import logging
import time

import requests
from django.conf import settings
from tenacity import retry, stop_after_attempt, wait_exponential

from .models import RawIngestionLog

logger = logging.getLogger("ingestion.tomtom")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def _fetch(lat, lng, api_key):
    url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
    params = {"key": api_key, "point": f"{lat},{lng}"}
    return requests.get(url, params=params, timeout=10)


def fetch_traffic_flow(intersection):
    """Fetch traffic flow for a single intersection. Returns dict or None."""
    api_key = settings.TOMTOM_API_KEY
    if not api_key:
        logger.warning("TOMTOM_API_KEY not set")
        return None

    endpoint = f"tomtom/flow/{intersection.intersection_id}"
    start = time.time()

    try:
        resp = _fetch(intersection.latitude, intersection.longitude, api_key)
        latency = (time.time() - start) * 1000

        RawIngestionLog.objects.create(
            source_name="tomtom",
            endpoint=endpoint,
            raw_payload=resp.json() if resp.status_code == 200 else None,
            status="success" if resp.status_code == 200 else "error",
            http_status=resp.status_code,
            error_message=None if resp.status_code == 200 else resp.text[:500],
            latency_ms=latency,
        )

        if resp.status_code != 200:
            return None

        data = resp.json()
        flow = data.get("flowSegmentData", {})
        return {
            "current_speed": flow.get("currentSpeed"),
            "free_flow_speed": flow.get("freeFlowSpeed"),
            "confidence": flow.get("confidence"),
            "current_travel_time": flow.get("currentTravelTime"),
            "free_flow_travel_time": flow.get("freeFlowTravelTime"),
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        RawIngestionLog.objects.create(
            source_name="tomtom",
            endpoint=endpoint,
            status="error",
            error_message=str(e)[:500],
            latency_ms=latency,
        )
        logger.error("TomTom fetch failed for %s: %s", intersection.intersection_id, e)
        return None
