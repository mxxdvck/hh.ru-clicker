from fastapi.testclient import TestClient

from app.config import CONFIG
from app.routes import app


client = TestClient(app)


def _seed_secrets(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_api_key", "secret-legacy-key")
    monkeypatch.setattr(CONFIG, "llm_profiles", [{
        "name": "Primary",
        "api_key": "secret-profile-key",
        "base_url": "https://example.test/v1",
        "model": "demo-model",
        "enabled": True,
    }])
    monkeypatch.setattr(CONFIG, "hh_proxy_url", "http://user:secret-pass@proxy.test:8080")
    monkeypatch.setattr("app.routes._API_KEY", "test-key")


def test_raw_config_get_masks_credentials(tmp_data_dir, monkeypatch):
    _seed_secrets(monkeypatch)

    response = client.get("/api/raw/config", headers={"X-API-Key": "test-key"})

    assert response.status_code == 200
    body = response.text
    assert "secret-legacy-key" not in body
    assert "secret-profile-key" not in body
    assert "secret-pass" not in body
    payload = response.json()
    assert payload["llm_api_key"] == "***"
    assert payload["llm_profiles"][0]["api_key"] == "***"
    assert payload["llm_profiles"][0]["key_set"] is True
    assert payload["hh_proxy_url"] == "***"


def test_masked_raw_config_roundtrip_preserves_secrets(tmp_data_dir, monkeypatch):
    _seed_secrets(monkeypatch)
    masked = client.get("/api/raw/config", headers={"X-API-Key": "test-key"}).json()

    response = client.post(
        "/api/raw/config",
        json={
            "llm_api_key": masked["llm_api_key"],
            "llm_profiles": masked["llm_profiles"],
            "hh_proxy_url": masked["hh_proxy_url"],
        },
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert CONFIG.llm_api_key == "secret-legacy-key"
    assert CONFIG.llm_profiles[0]["api_key"] == "secret-profile-key"
    assert CONFIG.hh_proxy_url == "http://user:secret-pass@proxy.test:8080"
