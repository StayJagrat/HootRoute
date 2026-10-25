import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for package in ("engine", "agents", "api"):
    sys.path.insert(0, str(ROOT / "services" / package))


@pytest.fixture(scope="session", autouse=True)
def isolated_providers():
    """Regression tests never use the developer's real provider credentials."""
    monkeypatch = pytest.MonkeyPatch()
    for name in ("ANTHROPIC_API_KEY", "APIFY_TOKEN", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "CARTESIA_API_KEY", "MAPILLARY_TOKEN"):
        monkeypatch.setenv(name, "")
    for name, value in {"HOOTROUTE_ENV": "development", "AGENT_RUNTIME": "inprocess", "HOURS_CHECK_MOCK": "0", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}.items():
        monkeypatch.setenv(name, value)
    yield
    monkeypatch.undo()
