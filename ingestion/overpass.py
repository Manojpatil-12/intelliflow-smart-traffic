"""Overpass API adapter — road network geometry. Run rarely, cache aggressively."""

import logging
import time

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from .models import RawIngestionLog

logger = logging.getLogger("ingestion.overpass")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=5, max=60))
def _fetch(query):
    return requests.post(OVERPASS_URL, data={"data": query}, timeout=30)


def fetch_road_network(bbox=None):
    """
    Fetch road network around Bengaluru.
    Respects Overpass fair-use policy — run weekly at most.
    """
    if bbox is None:
        bbox = "12.85,77.45,13.10,77.80"  # Bengaluru bounding box

    query = f"""
    [out:json][timeout:25];
    (
      way["highway"~"primary|secondary|tertiary"]({bbox});
    );
    out geom;
    """

    endpoint = "overpass/road_network"
    start = time.time()

    try:
        resp = _fetch(query)
        latency = (time.time() - start) * 1000

        RawIngestionLog.objects.create(
            source_name="overpass",
            endpoint=endpoint,
            raw_payload={"element_count": len(resp.json().get("elements", []))} if resp.status_code == 200 else None,
            status="success" if resp.status_code == 200 else "error",
            http_status=resp.status_code,
            error_message=None if resp.status_code == 200 else resp.text[:500],
            latency_ms=latency,
        )

        if resp.status_code != 200:
            return None

        data = resp.json()
        return data.get("elements", [])

    except Exception as e:
        latency = (time.time() - start) * 1000
        RawIngestionLog.objects.create(
            source_name="overpass",
            endpoint=endpoint,
            status="error",
            error_message=str(e)[:500],
            latency_ms=latency,
        )
        logger.error("Overpass fetch failed: %s", e)
        return None
