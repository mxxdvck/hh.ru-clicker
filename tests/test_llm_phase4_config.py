from fastapi.testclient import TestClient

from app.config import CONFIG, _coerce_config_value
from app.routes import app
from app.routes.settings import _safe_cast


client = TestClient(app)


def test_candidate_profile_is_allowlisted_and_trimmed(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_candidate_profile", {})
    response = client.post("/api/llm_config", json={"candidate_profile": {
        "salary_expectation": " 250000 ",
        "relocation": "нет",
        "secret_note": "must never survive",
        "location": "x" * 450,
    }})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert CONFIG.llm_candidate_profile["salary_expectation"] == "250000"
    assert CONFIG.llm_candidate_profile["relocation"] == "нет"
    assert "secret_note" not in CONFIG.llm_candidate_profile
    assert len(CONFIG.llm_candidate_profile["location"]) == 400


def test_llm_config_rejects_unsafe_confidence(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_auto_send_min_confidence", 0.88)
    response = client.post("/api/llm_config", json={"auto_send_min_confidence": 0.01})
    assert response.json()["ok"] is False
    assert CONFIG.llm_auto_send_min_confidence == 0.88

def test_generic_config_cast_cannot_lower_auto_safe_threshold(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_auto_send_min_confidence", 0.88)
    for caster in (_safe_cast, _coerce_config_value):
        try:
            caster("llm_auto_send_min_confidence", 0.01)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe confidence bypassed central guard")


def test_generic_candidate_profile_cast_strips_unknown_fields():
    raw = {"salary_expectation": "250000", "admin": "true", "token": "secret"}
    for caster in (_safe_cast, _coerce_config_value):
        assert caster("llm_candidate_profile", raw) == {"salary_expectation": "250000"}


def test_raw_config_uses_same_phase4_guards(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_auto_send_min_confidence", 0.88)
    monkeypatch.setattr(CONFIG, "llm_candidate_profile", {"relocation": "нет"})
    response = client.post("/api/raw/config", json={
        "llm_auto_send_min_confidence": 0.01,
        "llm_candidate_profile": {"salary_expectation": "250000", "hack": "yes"},
    })
    payload = response.json()
    assert payload["ok"] is False
    assert "llm_auto_send_min_confidence" in payload["errors"]
    assert CONFIG.llm_auto_send_min_confidence == 0.88
    assert CONFIG.llm_candidate_profile == {"salary_expectation": "250000"}