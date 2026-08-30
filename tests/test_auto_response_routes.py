import asyncio

import pytest

from app.routes import auto_response as routes


ACC = {"resume_hash": "resume-1"}


class JsonRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


@pytest.fixture(autouse=True)
def account(monkeypatch):
    monkeypatch.setattr(routes.bot, "_get_apply_acc", lambda idx: ACC if idx == 0 else None)


def test_status_combines_rules_and_statistics(monkeypatch):
    monkeypatch.setattr(routes.mobile_auto_response, "fetch_rules", lambda acc: [
        {"auto_response_id": "rule-1", "enabled": True},
    ])
    monkeypatch.setattr(routes.mobile_auto_response, "fetch_statistics", lambda acc, rule_id: {
        "counters": {"total": 8, "invitation": 2},
    })

    result = asyncio.run(routes.api_auto_response_status(0))

    assert result["ok"] is True
    assert result["statistics"]["rule-1"]["counters"]["invitation"] == 2


def test_create_requires_explicit_confirmation(monkeypatch):
    called = False

    def create(*args):
        nonlocal called
        called = True

    monkeypatch.setattr(routes.mobile_auto_response, "create_rule", create)
    result = asyncio.run(routes.api_auto_response_create(
        0, JsonRequest({"resume_id": "resume-1"}),
    ))

    assert result == {"ok": False, "error": "Требуется явное подтверждение"}
    assert called is False


def test_create_and_disable_rule(monkeypatch):
    created = {}
    updated = {}

    def create(acc, resume_id, filters):
        created.update(resume_id=resume_id, filters=filters)
        return {"auto_response_id": "rule-1", "enabled": True}

    def update(acc, rule_id, resume_id, *, enabled, filters):
        updated.update(rule_id=rule_id, resume_id=resume_id, enabled=enabled, filters=filters)
        return {"auto_response_id": rule_id, "enabled": enabled}

    monkeypatch.setattr(routes.mobile_auto_response, "create_rule", create)
    monkeypatch.setattr(routes.mobile_auto_response, "update_rule", update)
    create_result = asyncio.run(routes.api_auto_response_create(0, JsonRequest({
        "confirm": True,
        "filters": {"only_with_salary": True},
    })))
    update_result = asyncio.run(routes.api_auto_response_update(0, "rule-1", JsonRequest({
        "confirm": True,
        "enabled": False,
    })))

    assert create_result["ok"] is True
    assert created == {"resume_id": "resume-1", "filters": {"only_with_salary": True}}
    assert update_result["rule"]["enabled"] is False
    assert updated == {
        "rule_id": "rule-1", "resume_id": "resume-1",
        "enabled": False, "filters": None,
    }
