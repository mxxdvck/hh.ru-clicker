from app import manager
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
