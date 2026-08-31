import asyncio

from app.routes import career_visibility as routes


def test_career_route_uses_selected_account(monkeypatch):
    account = {"resume_hash": "r1"}
    monkeypatch.setattr(routes, "_account", lambda idx: account if idx == 0 else None)
    monkeypatch.setattr(routes, "fetch_career_radar", lambda acc: {"ok": True, "profession": "QA"})

    result = asyncio.run(routes.api_career_radar(0))

    assert result == {"ok": True, "profession": "QA"}


def test_visibility_route_passes_resume(monkeypatch):
    account = {"resume_hash": "r1"}
    calls = []
    monkeypatch.setattr(routes, "_account", lambda idx: account)
    monkeypatch.setattr(
        routes, "fetch_resume_visibility",
        lambda acc, rid: calls.append((acc, rid)) or {"ok": True},
    )

    assert asyncio.run(routes.api_resume_visibility(2)) == {"ok": True}
    assert calls == [(account, "r1")]


def test_new_routes_reject_unknown_account(monkeypatch):
    monkeypatch.setattr(routes, "_account", lambda idx: None)
    assert asyncio.run(routes.api_career_radar(-1))["ok"] is False
    assert asyncio.run(routes.api_resume_visibility(999))["ok"] is False
