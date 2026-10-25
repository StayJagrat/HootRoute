"""Optional street-image explanation. Imagery and Claude never affect route scores."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from math import cos, hypot, radians
import os
from pathlib import Path

import requests
from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool

from .settings import env

router = APIRouter()
MAPILLARY_IMAGES = "https://graph.mapillary.com/images"
CLAUDE_MESSAGES = "https://api.anthropic.com/v1/messages"
MAX_AGE = timedelta(days=3 * 365)
MAX_DISTANCE_M = 80


def _key(name: str) -> str | None:
    return env(name) or None


def _distance_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    return hypot((a_lat - b_lat) * 111_000, (a_lon - b_lon) * 111_000 * cos(radians(a_lat)))


def _capture_date(value: int | str | None) -> datetime | None:
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        pass
    return None


def _nearest_image(lat: float, lon: float, token: str) -> dict | None:
    # A roughly 120 m bounding box allows Mapillary's server to narrow the search.
    span_lat = 0.0011
    span_lon = 0.0011 / max(0.25, cos(radians(lat)))
    bbox = f"{lon-span_lon:.6f},{lat-span_lat:.6f},{lon+span_lon:.6f},{lat+span_lat:.6f}"
    response = requests.get(
        MAPILLARY_IMAGES,
        headers={"Authorization": f"OAuth {token}"},
        params={"bbox": bbox, "fields": "id,captured_at,computed_geometry,thumb_1024_url", "limit": 100},
        timeout=8,
    )
    response.raise_for_status()
    cutoff = datetime.now(timezone.utc) - MAX_AGE
    choices = []
    for item in response.json().get("data", []):
        point = item.get("computed_geometry", {}).get("coordinates", [])
        captured = _capture_date(item.get("captured_at"))
        if len(point) != 2 or not captured or captured < cutoff or not item.get("thumb_1024_url"):
            continue
        distance = _distance_m(lat, lon, point[1], point[0])
        if distance <= MAX_DISTANCE_M:
            choices.append((distance, -captured.timestamp(), item, captured))
    if not choices:
        return None
    distance, _, image, captured = min(choices, key=lambda row: row[:2])
    return {
        "id": image["id"],
        "imageUrl": image["thumb_1024_url"],
        "capturedAt": captured.date().isoformat(),
        "distanceM": round(distance),
        "sourceUrl": f"https://www.mapillary.com/app/?pKey={image['id']}",
    }


def _describe(image_url: str, key: str) -> str | None:
    response = requests.post(
        CLAUDE_MESSAGES,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={
            "model": "claude-sonnet-5-5",
            "max_tokens": 120,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "url", "url": image_url}},
                {"type": "text", "text": "Describe only visible street lamps, lit or shuttered storefronts, and scaffolding in at most two plain sentences. Say when a detail cannot be seen. Do not infer current conditions or rate personal safety."},
            ]}],
        },
        timeout=25,
    )
    response.raise_for_status()
    return " ".join(block["text"] for block in response.json().get("content", []) if block.get("type") == "text").strip() or None


@lru_cache(maxsize=64)
def _analyze(lat: float, lon: float) -> dict:
    mapillary = _key("MAPILLARY_ACCESS_TOKEN") or _key("MAPILLARY_TOKEN")
    claude = _key("ANTHROPIC_API_KEY")
    if not mapillary or not claude:
        return {"status": "missing_key", "message": "Street-level image explanation is unavailable; a provider key is missing.", "usedForScore": False}
    try:
        image = _nearest_image(lat, lon, mapillary)
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return {"status": "unavailable", "message": "Street-level imagery is unavailable right now.", "usedForScore": False}
    if image is None:
        return {"status": "no_recent_image", "message": "No recent Mapillary image was found within 80 m.", "usedForScore": False}
    try:
        explanation = _describe(image["imageUrl"], claude)
    except (requests.RequestException, ValueError, KeyError, TypeError):
        explanation = None
    if not explanation:
        return {"status": "analysis_unavailable", "message": "Image found, but its visual explanation is unavailable.", "usedForScore": False, **image}
    return {"status": "available", "message": explanation, "usedForScore": False, **image}


@router.get("/api/block-vision")
async def block_vision(lat: float = Query(ge=37.76, le=37.81), lon: float = Query(ge=-122.44, le=-122.38)):
    """Return nearby captured imagery with an explanation, or a clear missing-data state."""
    return await run_in_threadpool(_analyze, round(lat, 5), round(lon, 5))
