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
    assert asyncio.run(discovery.api_operations_summary(99))["ok"] is False


def test_operations_summary_separates_live_cycle_outcome_and_ledger(monkeypatch):
    class State:
        filter_stats = {"raw_collected": 120, "accepted": 18}
        vacancies_queue = ["1", "2", "3"]
        daily_sent = 7
        status = "search_only"
        hh_stats_updated = "now"
        hh_viewed = 11

    async def fake_conversion(idx):
        return {"ok": True, "applied": 40, "interviews": 5, "conversion_percent": 12.5}

    monkeypatch.setattr(discovery, "_acc", lambda idx: {"name": "mine"})
    monkeypatch.setattr(discovery, "_state", lambda idx: State())
    monkeypatch.setattr(discovery, "api_conversion", fake_conversion)
    monkeypatch.setattr(discovery, "get_status_counts", lambda name: {
        "applied": 40, "interrupted": 2, "failed_permanent": 1,
    })

    result = asyncio.run(discovery.api_operations_summary(0))
    assert result["cycle"] == {
        "found": 120, "filtered": 18, "queue": 3,
        "sent_today": 7, "status": "search_only",
    }
    assert result["outcome"] == {
        "applied": 40, "viewed": 11, "interviews": 5,
        "conversion_percent": 12.5,
    }
    assert result["ledger"]["statuses"]["interrupted"] == 2
    assert result["ledger"]["statuses"]["failed_permanent"] == 1
    assert result["ledger"]["total"] == 43


def test_operations_summary_does_not_invent_unknown_hh_views(monkeypatch):
    class State:
        filter_stats = {}
        daily_sent = 0
        status = "idle"
        hh_stats_updated = None
        hh_viewed = 0

    async def fake_conversion(idx):
        return {"ok": True, "applied": 0, "interviews": 0, "conversion_percent": 0}

    monkeypatch.setattr(discovery, "_acc", lambda idx: {"name": "mine"})
    monkeypatch.setattr(discovery, "_state", lambda idx: State())
    monkeypatch.setattr(discovery, "api_conversion", fake_conversion)
    monkeypatch.setattr(discovery, "get_status_counts", lambda name: {})

    result = asyncio.run(discovery.api_operations_summary(0))
    assert result["cycle"]["found"] is None
    assert result["cycle"]["filtered"] is None
    assert result["cycle"]["queue"] is None
    assert result["outcome"]["viewed"] is None
    assert result["sources"]["viewed"] == "unavailable"
