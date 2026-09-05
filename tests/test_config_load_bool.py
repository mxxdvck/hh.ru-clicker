import json

from app import config


def test_load_config_parses_false_strings_as_false(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "llm_enabled": "false",
        "llm_auto_send": "0",
        "llm_fill_questionnaire": "no",
        "auto_apply_tests": "off",
        "use_oauth_apply": "false",
        "search_only_mode": "false",
        "llm_openclaw_enabled": "false",
    }), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    for key in ("llm_enabled", "llm_auto_send", "llm_fill_questionnaire",
                "auto_apply_tests", "use_oauth_apply", "search_only_mode"):
        monkeypatch.setattr(config.CONFIG, key, True)
    monkeypatch.setattr(config.CONFIG, "llm_openclaw_enabled", True)

    config.load_config()

    assert config.CONFIG.llm_enabled is False
    assert config.CONFIG.llm_auto_send is False
    assert config.CONFIG.llm_fill_questionnaire is False
    assert config.CONFIG.auto_apply_tests is False
    assert config.CONFIG.use_oauth_apply is False
    assert config.CONFIG.search_only_mode is False
    assert config.CONFIG.llm_openclaw_enabled is False


def test_load_config_ignores_invalid_bool_instead_of_enabling_it(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"llm_auto_send": "definitely-not-a-bool"}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    monkeypatch.setattr(config.CONFIG, "llm_auto_send", False)

    config.load_config()

    assert config.CONFIG.llm_auto_send is False


def test_config_snapshot_contains_search_only_mode(monkeypatch):
    monkeypatch.setattr(config.CONFIG, "search_only_mode", True)
    snap = config.config_snapshot()
    assert snap["search_only_mode"] is True


def test_load_config_migrates_run_limit_from_daily(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"daily_apply_limit": 50}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    monkeypatch.setattr(config.CONFIG, "daily_apply_limit", 20)
    monkeypatch.setattr(config.CONFIG, "run_apply_limit", 20)

    config.load_config()

    assert config.CONFIG.daily_apply_limit == 50
    assert config.CONFIG.run_apply_limit == 50


def test_config_snapshot_contains_run_apply_limit(monkeypatch):
    monkeypatch.setattr(config.CONFIG, "run_apply_limit", 17)
    snap = config.config_snapshot()
    assert snap["run_apply_limit"] == 17
