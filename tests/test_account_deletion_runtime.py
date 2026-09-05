import asyncio
import threading

from app.config import accounts_data
from app.instances import bot
from app.routes import settings
from app.routes import accounts as account_routes


class _Request:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class _State:
    def __init__(self, name):
        self.name = name
        self.short = name
        self.acc = {"name": name, "short": name, "resume_hash": name + "-rh",
                    "cookies": {"hhtoken": name}}
        self._state_lock = threading.Lock()
        self._deleted = False
        self.paused = False
        self.cookies_expired = False


def test_raw_account_delete_prunes_runtime_snapshot(monkeypatch):
    old_accounts = list(accounts_data)
    old_states = list(bot.account_states)
    keep, removed = _State("keep"), _State("removed")
    accounts_data[:] = [dict(keep.acc), dict(removed.acc)]
    bot.account_states[:] = [keep, removed]
    monkeypatch.setattr(settings, "save_accounts", lambda: None)
    try:
        result = asyncio.run(settings.api_raw_accounts_set(_Request([dict(keep.acc)])))
        assert result["ok"] is True
        assert [s.name for s in bot.account_states] == ["keep"]
        assert removed._deleted is True
        assert removed.paused is True
        assert [a["name"] for a in accounts_data] == ["keep"]
    finally:
        accounts_data[:] = old_accounts
        bot.account_states[:] = old_states


def test_frontend_reindexes_and_resyncs_account_controls():
    source = open("static/js/app.js", encoding="utf-8").read()
    assert "removeAccountFromCurrentSnapshot(idx)" in source
    assert "Number(a.idx) - 1" in source
    assert "JobStatusSyncAccounts" in source
    assert "delete _AccDiagCache[idx]" in source

    job_status = open("static/js/features/job_status.js", encoding="utf-8").read()
    assert "window.JobStatusSyncAccounts = jsSyncAccounts" in job_status
    assert "const loaded = jsFillAccounts()" in job_status
    assert "jsLoadDiagnostics()" in job_status
    hedi = open("static/js/features/hedi.js", encoding="utf-8").read()
    assert "HediState.idx = null" in hedi


def test_safety_toggle_is_per_account_and_persisted(monkeypatch):
    old_accounts = list(accounts_data)
    old_states = list(bot.account_states)
    first, second = _State("first"), _State("second")
    first.safety_enabled = False
    second.safety_enabled = False
    accounts_data[:] = [dict(first.acc), dict(second.acc)]
    bot.account_states[:] = [first, second]
    monkeypatch.setattr(account_routes, "save_accounts", lambda: None)
    try:
        result = asyncio.run(account_routes.api_safety_toggle(0))
        assert result == {"ok": True, "safety_enabled": True}
        assert first.safety_enabled is True
        assert second.safety_enabled is False
        assert accounts_data[0]["safety_enabled"] is True
        assert "safety_enabled" not in accounts_data[1]
    finally:
        accounts_data[:] = old_accounts
        bot.account_states[:] = old_states


def test_card_delete_removes_runtime_state_and_recent_rows(monkeypatch):
    old_accounts = list(accounts_data)
    old_states = list(bot.account_states)
    old_recent = bot.recent_responses
    first, second = _State("first"), _State("second")
    accounts_data[:] = [dict(first.acc), dict(second.acc)]
    bot.account_states[:] = [first, second]
    bot.recent_responses = type(old_recent)([
        {"id": "1", "acc": "first"}, {"id": "2", "acc": "second"}
    ], maxlen=old_recent.maxlen)
    monkeypatch.setattr(account_routes, "save_accounts", lambda: None)
    monkeypatch.setattr(bot, "_add_log", lambda *args: None)
    monkeypatch.setattr("app.oauth.invalidate_oauth_token", lambda *args: None)
    try:
        result = asyncio.run(account_routes.api_account_delete(0))
        assert result == {"ok": True}
        assert [s.name for s in bot.account_states] == ["second"]
        assert [a["name"] for a in accounts_data] == ["second"]
        assert list(bot.recent_responses) == [{"id": "2", "acc": "second"}]
        assert first._deleted is True and first.paused is True
    finally:
        accounts_data[:] = old_accounts
        bot.account_states[:] = old_states
        bot.recent_responses = old_recent
