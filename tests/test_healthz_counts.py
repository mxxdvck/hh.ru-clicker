import asyncio

from app.instances import bot
from app.routes import healthz


def test_healthz_distinguishes_saved_and_active_sessions(monkeypatch):
    monkeypatch.setattr(bot, "account_states", [])
    monkeypatch.setattr(bot, "temp_sessions", [{"name": "saved"}])
    monkeypatch.setattr(bot, "temp_states", {})

    result = asyncio.run(healthz())

    assert result == {
        "ok": True,
        "accounts": 0,
        "temp_sessions": 1,
        "active_temp_sessions": 0,
    }
