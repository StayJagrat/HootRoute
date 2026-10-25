"""Pilot area: central San Francisco (Embarcadero to Civic Center, Mission St to Broadway). One place to change it."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "data" / "cache"
_BBOX_FILE = CACHE / "bbox.json"
# south, west, north, east. data/cache/bbox.json (written by scripts/fetch_data.py) overrides this default.
BBOX = tuple(json.loads(_BBOX_FILE.read_text())) if _BBOX_FILE.exists() else (37.7690, -122.4250, 37.7990, -122.3910)
WALK_SPEED = 1.35        # m/s
STEP = 10.0              # route sampling distance, m
WEIGHTS = dict(places=20, gaps=15, help=15, light=20, main=10, transit=10, turns=10)


def _tiles(bbox, ny=2, nx=2):
    s, w, n, e = bbox; out = []
    for i in range(ny):
        for j in range(nx):
            out.append((s + (n - s) * i / ny - 0.0004, w + (e - w) * j / nx - 0.0004, s + (n - s) * (i + 1) / ny + 0.0004, w + (e - w) * (j + 1) / nx + 0.0004))
    return out


TILES = _tiles(BBOX)
