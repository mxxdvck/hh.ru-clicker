from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_phase5_account_card_bridge_is_explicit():
    app = _source("static/js/app.js")
    assert "hh:account-card-updated" in app


def test_phase5_migrated_features_do_not_monkey_patch_render_globals():
    feat3 = _source("static/js/features/feat3_skills.js")
    feat4 = _source("static/js/features/feat4_counters.js")
    feat7 = _source("static/js/features/feat7_mode.js")

    assert "window.updateCard =" not in feat3
    assert "window.updateCard =" not in feat7
    assert "window.buildSessList =" not in feat7
    assert "window.buildAccCookiesList =" not in feat7
    assert "window.renderHeader =" not in feat4

    assert "hh:account-card-updated" in feat3
    assert "hh:account-card-updated" in feat7
    assert "hh:snapshot" in feat4
    assert "hh:snapshot" in feat7
