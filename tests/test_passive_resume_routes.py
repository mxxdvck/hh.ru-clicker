"""Regression tests for reading resumes from an inactive browser session."""

import asyncio
from types import SimpleNamespace

from app import routes
from app.routes import accounts
from app.instances import bot


def test_resume_text_uses_persistent_temp_session_without_worker(monkeypatch):
    """The read-only endpoint must not require AccountState/bot_active."""
    monkeypatch.setattr(bot, "account_states", [])
    monkeypatch.setattr(bot, "temp_states", {})
    monkeypatch.setattr(bot, "temp_sessions", [{
        "name": "Browser",
        "resume_hash": "resume-1",
        "cookies": {},
        "mode": "auto",
        "bot_active": False,
    }])

    class ReadOnlyClient:
        def fetch_resume(self):
            return '{"title":"1С-разработчик / Программист 1С"}'

    monkeypatch.setattr(accounts, "get_client", lambda acc: ReadOnlyClient())

    result = asyncio.run(accounts.api_resume_text(0))

    assert result["ok"] is True
    assert result["resume_hash"] == "resume-1"
    assert "1С-разработчик" in result["text"]


def test_all_resumes_uses_oauth_list_after_legacy_ssr_is_empty(monkeypatch):
    """The new profile flow is supported without mutating session state."""
    monkeypatch.setattr(bot, "account_states", [])
    monkeypatch.setattr(bot, "temp_sessions", [{
        "name": "Browser",
        "resume_hash": "resume-1",
        "cookies": {},
        "mode": "auto",
        "bot_active": False,
    }])
    monkeypatch.setattr(
        accounts.HH,
        "get",
        lambda *args, **kwargs: SimpleNamespace(status_code=200, text="<html></html>"),
    )
    monkeypatch.setattr(
        routes.accounts,
        "mobile_request",
        lambda *args, **kwargs: {
            "items": [{
                "id": "resume-1",
                "title": "1С-разработчик / Программист 1С",
                "status": "published",
                "experience": [{}],
                "key_skills": [{"name": "1С"}],
            }]
        },
    )

    result = asyncio.run(accounts.api_all_resumes(0))

    assert result["total"] == 1
    assert result["resumes"][0]["hash"] == "resume-1"
    assert result["resumes"][0]["title"] == "1С-разработчик / Программист 1С"
    assert result["resumes"][0]["status"] == "published"
    assert result["resumes"][0]["experience_count"] == 1
