"""Speech out through Cartesia Sonic. The browser never sees the key; with no key the PWA falls back to on-device speech."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .settings import settings

router = APIRouter(prefix="/api/voice")
CARTESIA_TTS = "https://api.cartesia.ai/tts/bytes"
CARTESIA_VERSION = "2026-08-14"


class SayReq(BaseModel):
    text: str = Field(min_length=1, max_length=400)


@router.post("/tts")
async def tts(req: SayReq):
    if not settings.tts_enabled: raise HTTPException(501, "Cartesia is not configured; use on-device speech.")
    body = {"model_id": settings.cartesia_model, "transcript": req.text, "voice": {"id": settings.cartesia_voice},
            "output_format": {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000}}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(CARTESIA_TTS, json=body, headers={"Authorization": f"Bearer {settings.cartesia_key}", "Cartesia-Version": CARTESIA_VERSION})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Cartesia unreachable ({type(e).__name__})") from e
    if r.status_code != 200: raise HTTPException(502, f"Cartesia answered {r.status_code}")
    return Response(r.content, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
