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


def _production() -> bool: return env("HOOTROUTE_ENV").lower() == "production"


@dataclass(frozen=True)
class Settings:
    production: bool = field(default_factory=_production)                                # HOOTROUTE_ENV=production: refuse open defaults
    public_url: str = field(default_factory=lambda: env("PUBLIC_URL").rstrip("/"))       # e.g. https://hootroute.example.com; used in guardian links and SMS
    db_path: Path = field(default_factory=lambda: Path(env("DB_PATH", str(ROOT / "data" / "hootroute.db"))))
    admin_token: str = field(default_factory=lambda: env("ADMIN_TOKEN"))                 # empty = control room open (local development only)
    demo_rooms: bool = field(default_factory=lambda: _flag("ALLOW_DEMO_ROOMS", not _production()))    # relay unregistered rooms for the offline DemoEngine
    rate_limits: bool = field(default_factory=lambda: _flag("RATE_LIMITS", True))        # per-IP limits on planning and paid endpoints
    apify_daily_runs: int = field(default_factory=lambda: int(env("APIFY_DAILY_RUNS", "25")))   # paid hours checks per day, whole gateway
    sms_allowlist: tuple[str, ...] = field(default_factory=lambda: tuple(n.strip() for n in env("SMS_ALLOWLIST").split(",") if n.strip()))
    max_notifications: int = field(default_factory=lambda: int(env("MAX_NOTIFICATIONS_PER_WALK", "6")))      # SMS + calls per walk
    agent_runtime: str = field(default_factory=lambda: env("AGENT_RUNTIME", "inprocess"))  # inprocess | uagents
    uagents_bridge_url: str = field(default_factory=lambda: env("UAGENTS_BRIDGE_URL", "http://127.0.0.1:8110").rstrip("/"))
    bridge_secret: str = field(default_factory=lambda: env("BRIDGE_SECRET"))
    position_retention_h: float = field(default_factory=lambda: float(env("POSITION_RETENTION_HOURS", "24")))
    plan_ttl_s: int = field(default_factory=lambda: int(env("PLAN_TTL_SECONDS", "1800")))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(o.strip() for o in env("CORS_ORIGINS", env("PUBLIC_URL").rstrip("/") if _production() else "*").split(",") if o.strip()))
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

    def problems(self) -> list[str]:
        """Configuration that must not reach a public deployment. In production the gateway refuses to start with any of these."""
        out = []
        if self.agent_runtime == "uagents" and len(self.bridge_secret) < 16: out.append("BRIDGE_SECRET (16+ characters) is required when AGENT_RUNTIME=uagents")
        if self.production:
            if len(self.admin_token) < 16: out.append("ADMIN_TOKEN (16+ characters) is required in production")
            if not self.public_url.startswith("https://"): out.append("PUBLIC_URL must be an https:// origin in production")
            if "*" in self.cors_origins: out.append("CORS_ORIGINS must list the app's origins in production, not *")
            if self.sms_enabled and not self.sms_allowlist: out.append("SMS_ALLOWLIST is required in production when Twilio is configured")
        return out


settings = Settings()
