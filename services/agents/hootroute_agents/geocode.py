"""Address and place lookup beyond the offline map: Geoapify when a key is configured, else Photon (keyless), both
limited to San Francisco. The offline engine search knows OSM names; this finds "SF Public Library main branch",
"16th St Mission BART" or "562 Sutter St" at the right spot instead of a street's midpoint."""
from __future__ import annotations

import logging

import httpx

from .config import env

log = logging.getLogger("hootroute.geocode")
RECT = (-122.52, 37.70, -122.35, 37.84)          # west, south, east, north


def _in_sf(lat: float, lon: float) -> bool: return RECT[1] <= lat <= RECT[3] and RECT[0] <= lon <= RECT[2]


async def geocode(q: str, limit: int = 5, timeout: float = 4.0) -> list[dict]:
    """[{name, detail, lat, lon, source}] inside San Francisco. Never raises; an empty list means not found or offline."""
    q = q.strip()[:120]
    if len(q) < 3: return []
    key = env("GEOAPIFY_KEY") or env("VITE_GEOAPIFY_KEY")
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            if key:
                r = await c.get("https://api.geoapify.com/v1/geocode/search", params={
                    "text": q, "filter": f"rect:{RECT[0]},{RECT[1]},{RECT[2]},{RECT[3]}", "bias": "proximity:-122.4194,37.7749",
                    "limit": limit, "lang": "en", "format": "json", "apiKey": key})
                rows = r.json().get("results", []) if r.status_code == 200 else []
                out = [{"name": x.get("name") or x.get("address_line1") or x.get("formatted", q), "detail": x.get("address_line2") or x.get("formatted") or "San Francisco",
                        "lat": float(x["lat"]), "lon": float(x["lon"]), "source": "geoapify"} for x in rows if "lat" in x and "lon" in x]
            else:
                r = await c.get("https://photon.komoot.io/api/", params={"q": q, "bbox": ",".join(map(str, RECT)), "lat": 37.7749, "lon": -122.4194, "limit": limit, "lang": "en"})
                feats = r.json().get("features", []) if r.status_code == 200 else []
                out = []
                for f in feats:
                    c2 = (f.get("geometry") or {}).get("coordinates") or []; p = f.get("properties") or {}
                    if len(c2) < 2: continue
                    label = p.get("name") or " ".join(str(x) for x in (p.get("housenumber"), p.get("street")) if x) or q
                    out.append({"name": label, "detail": " ".join(str(x) for x in (p.get("street"), p.get("district") or p.get("city")) if x) or "San Francisco",
                                "lat": float(c2[1]), "lon": float(c2[0]), "source": "photon"})
    except (httpx.HTTPError, ValueError, KeyError) as e:
        log.info("geocoder unavailable: %s", type(e).__name__); return []
    return [x for x in out if _in_sf(x["lat"], x["lon"])][:limit]
