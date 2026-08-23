"""Open-Meteo weather API adapter (no API key required)."""

import logging
import time

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from core.models import Weather
from .models import RawIngestionLog

logger = logging.getLogger("ingestion.openmeteo")

# Bengaluru city centre
DEFAULT_LAT = 12.9716
DEFAULT_LNG = 77.5946


def _wmo_to_condition(code):
    """Map WMO weather codes to simple condition strings."""
    if code in (0, 1):
        return "Clear"
    elif code in (2, 3):
        return "Cloudy"
    elif code in (45, 48):
        return "Fog"
    elif code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
        return "Rain"
    elif code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    elif code in (95, 96, 99):
        return "Thunderstorm"
    return "Clear"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def _fetch():
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": DEFAULT_LAT,
        "longitude": DEFAULT_LNG,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
        "daily": "weather_code,temperature_2m_max,precipitation_sum",
        "timezone": "Asia/Kolkata",
        "forecast_days": 2,
    }
    return requests.get(url, params=params, timeout=10)


def fetch_weather():
    """Fetch current + forecast weather. Returns dict or None."""
    endpoint = "openmeteo/forecast"
    start = time.time()

    try:
        resp = _fetch()
        latency = (time.time() - start) * 1000

        RawIngestionLog.objects.create(
            source_name="openmeteo",
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
        current = data.get("current", {})

        from django.utils import timezone as tz
        Weather.objects.create(
            recorded_at=tz.now(),
            latitude=DEFAULT_LAT,
            longitude=DEFAULT_LNG,
            temp_celsius=current.get("temperature_2m"),
            humidity=current.get("relative_humidity_2m"),
            condition=_wmo_to_condition(current.get("weather_code", 0)),
            wind_kph=current.get("wind_speed_10m"),
            precipitation_mm=current.get("precipitation"),
            source="openmeteo",
        )

        return {
            "condition": _wmo_to_condition(current.get("weather_code", 0)),
            "temp": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        RawIngestionLog.objects.create(
            source_name="openmeteo",
            endpoint=endpoint,
            status="error",
            error_message=str(e)[:500],
            latency_ms=latency,
        )
        logger.error("Open-Meteo fetch failed: %s", e)
        return None
