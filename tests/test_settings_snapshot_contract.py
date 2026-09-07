from app import manager, state as state_mod
from app.config import CONFIG, _CONFIG_KEYS


def _empty_bot(monkeypatch):
    monkeypatch.setattr(manager, "load_browser_sessions", lambda: [])
    monkeypatch.setattr(manager, "get_stats", lambda: {"total": 0, "tests": 0})
    monkeypatch.setattr(manager, "get_llm_status_summary", lambda: {})
    return manager.BotManager()


def test_dashboard_snapshot_contains_all_nonsecret_runtime_config(monkeypatch):
    bot = _empty_bot(monkeypatch)
    config = bot.get_state_snapshot()["config"]

    expected = set(_CONFIG_KEYS) - {"hh_proxy_url"}
    assert expected <= set(config)
    assert "hh_proxy_url" not in config


def test_dashboard_snapshot_preserves_gender_region_and_run_limit(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "male")
    monkeypatch.setattr(CONFIG, "hh_region", "moscow")
    monkeypatch.setattr(CONFIG, "run_apply_limit", 7)

    config = _empty_bot(monkeypatch).get_state_snapshot()["config"]

    assert config["llm_applicant_gender"] == "male"
    assert config["hh_region"] == "moscow"
    assert config["run_apply_limit"] == 7


def test_dashboard_snapshot_includes_search_filter_breakdown(monkeypatch):
    bot = _empty_bot(monkeypatch)
    state = manager.AccountState(
        {"name": "Test", "short": "T", "color": "yellow", "urls": []}
    )
    state.filter_stats = {
        "raw_collected": 248,
        "duplicates": 103,
        "missing_title": 29,
        "accepted": 6,
    }
    bot.account_states = [state]

    account = bot.get_state_snapshot()["accounts"][0]

    assert account["filter_stats"] == state.filter_stats


def test_inactive_temp_session_keeps_persisted_daily_count(monkeypatch):
    bot = _empty_bot(monkeypatch)
    bot.temp_sessions = [{"name": "Test", "short": "T", "resume_hash": "r", "bot_active": False}]
    monkeypatch.setattr(manager, "get_account_applied", lambda name: {
        str(i): {"at": "2099-01-01T12:00:00+03:00"} for i in range(12)
    })
    monkeypatch.setattr(manager, "_today_msk", lambda: "2099-01-01")
    monkeypatch.setattr(manager, "count_applied_today", lambda name, day: 12)
    account = bot.get_state_snapshot()["accounts"][0]
    assert account["bot_active"] is False
    assert account["daily_sent"] == 12
    assert account["total_applied"] == 12


def test_account_state_rebuilds_daily_count_from_ledger(monkeypatch):
    monkeypatch.setattr(state_mod, "count_applied_today", lambda name, day: 12)
    monkeypatch.setattr(state_mod, "get_account_applied", lambda name: {})
    state = state_mod.AccountState({"name": "Test", "short": "T", "color": "yellow", "urls": []})
    assert state.daily_sent == 12


def test_dashboard_snapshot_search_preview_keeps_phase5_metadata(monkeypatch):
    bot = _empty_bot(monkeypatch)
    state = manager.AccountState({"name": "Test", "short": "T", "color": "yellow", "urls": []})
    state.vacancies_queue = ["101"]
    state.vacancy_meta["101"] = {
        "title": "1C Developer", "company": "Acme", "salary_from": 220000,
        "source_url": "https://hh.ru/search/vacancy?text=1C", "source_query": "1C",
        "published_at": "2026-09-06T12:00:00+03:00", "schedules": ["remote"],
        "has_test": True, "response_letter_required": True,
        "hr_online": "2026-09-06T13:00:00+03:00", "chat_write_possibility": "ENABLED",
        "quick_responses_allowed": True, "accredited_it_employer": True,
    }
    bot.account_states = [state]

    item = bot.get_state_snapshot()["accounts"][0]["search_preview"][0]
    assert item["source_query"] == "1C"
    assert item["published_at"].startswith("2026-09-06")
    assert item["schedules"] == ["remote"]
    assert item["has_test"] is True
    assert item["hr_online"]
    assert item["quick_responses_allowed"] is True
    assert item["accredited_it_employer"] is True
