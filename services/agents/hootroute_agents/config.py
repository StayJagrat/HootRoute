"""Environment for the agents: process env first, then the git-ignored repo-root .env (parsed, never exported or printed)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _dotenv() -> dict[str, str]:
    path = ROOT / ".env"; out: dict[str, str] = {}
    if not path.exists(): return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1); v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


_FILE = _dotenv()


def env(name: str, default: str = "") -> str:
    """A variable set in the process environment wins even when empty (tests blank keys that way)."""
    if name in os.environ: return os.environ[name] or default
    return _FILE.get(name) or default
