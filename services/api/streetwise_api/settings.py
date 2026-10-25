"""Runtime configuration. Every value comes from the environment or the git-ignored repo-root .env; nothing secret lives in code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _dotenv() -> dict[str, str]:
    """Parse ROOT/.env without exporting it to a shell (a malformed line must never echo a value)."""
    path = ROOT / ".env"; out: dict[str, str] = {}
    if not path.exists(): return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"\'')
    return out


_FILE = _dotenv()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name) or _FILE.get(name) or default


def _flag(name: str, default: bool) -> bool:
    v = env(name, "1" if default else "0").lower()
    return v in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    public_url: str = field(default_factory=lambda: env("PUBLIC_URL").rstrip("/"))       # e.g. https://streetwise.example.com; used in guardian links and SMS
    db_path: Path = field(default_factory=lambda: Path(env("DB_PATH", str(ROOT / "data" / "streetwise.db"))))
    admin_token: str = field(default_factory=lambda: env("ADMIN_TOKEN"))                 # empty = control room open (local development only)
    demo_rooms: bool = field(default_factory=lambda: _flag("ALLOW_DEMO_ROOMS", True))    # relay unregistered rooms for the offline DemoEngine
    agent_runtime: str = field(default_factory=lambda: env("AGENT_RUNTIME", "inprocess"))  # inprocess | uagents
    uagents_bridge_url: str = field(default_factory=lambda: env("UAGENTS_BRIDGE_URL", "http://127.0.0.1:8110").rstrip("/"))
    bridge_secret: str = field(default_factory=lambda: env("BRIDGE_SECRET"))
    position_retention_h: float = field(default_factory=lambda: float(env("POSITION_RETENTION_HOURS", "24")))
    plan_ttl_s: int = field(default_factory=lambda: int(env("PLAN_TTL_SECONDS", "1800")))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(o.strip() for o in env("CORS_ORIGINS", "*").split(",") if o.strip()))
    # optional providers: each feature reports "not configured" instead of failing
    twilio_sid: str = field(default_factory=lambda: env("TWILIO_ACCOUNT_SID"))
    twilio_token: str = field(default_factory=lambda: env("TWILIO_AUTH_TOKEN"))
    twilio_from: str = field(default_factory=lambda: env("TWILIO_FROM_NUMBER"))
    apify_token: str = field(default_factory=lambda: env("APIFY_TOKEN"))
    cartesia_key: str = field(default_factory=lambda: env("CARTESIA_API_KEY"))
    cartesia_voice: str = field(default_factory=lambda: env("CARTESIA_VOICE_ID", "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"))   # Cartesia stock voice; override with your own
    cartesia_model: str = field(default_factory=lambda: env("CARTESIA_MODEL", "sonic-3.6"))

    @property
    def sms_enabled(self) -> bool: return bool(self.twilio_sid and self.twilio_token and self.twilio_from)

    @property
    def tts_enabled(self) -> bool: return bool(self.cartesia_key and self.cartesia_voice)


settings = Settings()
