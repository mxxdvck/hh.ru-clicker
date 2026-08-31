import asyncio

from app.routes import discovery


def test_conversion_counts_only_matching_account_and_vacancies(monkeypatch):
    monkeypatch.setattr(discovery, "_acc", lambda idx: {"name": "mine"})
    monkeypatch.setattr(discovery, "_state", lambda idx: None)
    monkeypatch.setattr(discovery, "get_applied_list", lambda limit: [
        {"account": "mine", "vacancy_id": "1"},
        {"account": "mine", "vacancy_id": "2"},
        {"account": "other", "vacancy_id": "3"},
    ])
    monkeypatch.setattr(discovery, "get_interviews_list", lambda **kwargs: [
        {"vacancy_id": "2"}, {"vacancy_id": "3"},
    ])
    result = asyncio.run(discovery.api_conversion(0))
    assert result == {"ok": True, "applied": 2, "interviews": 1,
                      "conversion_percent": 50.0}


def test_conversion_uses_hh_counter_for_legacy_interview_records(monkeypatch):
    class State:
        hh_interviews = 3
    monkeypatch.setattr(discovery, "_acc", lambda idx: {"name": "mine"})
    monkeypatch.setattr(discovery, "_state", lambda idx: State())
    monkeypatch.setattr(discovery, "get_applied_list", lambda limit: [
        {"account": "mine", "vacancy_id": str(i)} for i in range(10)
    ])
    monkeypatch.setattr(discovery, "get_interviews_list", lambda **kwargs: [
        {"neg_id": "legacy-without-vacancy"},
    ])
    result = asyncio.run(discovery.api_conversion(0))
    assert result["interviews"] == 3
    assert result["conversion_percent"] == 30.0


def test_discovery_routes_reject_unknown_account(monkeypatch):
    monkeypatch.setattr(discovery, "_acc", lambda idx: None)
    assert asyncio.run(discovery.api_hidden(-1))["ok"] is False
    assert asyncio.run(discovery.api_bell_notifications(99))["ok"] is False
    assert asyncio.run(discovery.api_conversion(99))["ok"] is False
