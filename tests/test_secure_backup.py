import json

from fastapi.testclient import TestClient

from app.routes import app
from app import secure_store

client = TestClient(app)


def _seed(data_dir):
    (data_dir / "config.json").write_text(
        json.dumps({"llm_api_key": "secret-llm-key", "llm_profiles": []}),
        encoding="utf-8",
    )
    (data_dir / "accounts.json").write_text(
        json.dumps([{"name": "demo", "cookies": {"hhtoken": "secret-cookie"}}]),
        encoding="utf-8",
    )
    (data_dir / "browser_sessions.json").write_text("[]", encoding="utf-8")
    (data_dir / "oauth_tokens.json").write_text(
        json.dumps({"r1": {"access_token": "secret-access", "refresh_token": "secret-refresh"}}),
        encoding="utf-8",
    )


def test_backup_is_encrypted_with_data_key(tmp_data_dir, monkeypatch):
    _seed(tmp_data_dir)
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "backup-test-key")
    monkeypatch.setattr("app.routes._API_KEY", "test-key")

    response = client.get("/api/backup", headers={"X-API-Key": "test-key"})

    assert response.status_code == 200
    raw = response.text
    assert "secret-llm-key" not in raw
    assert "secret-cookie" not in raw
    assert "secret-access" not in raw
    envelope = response.json()
    assert secure_store.is_secure_envelope(envelope)
    decoded = secure_store.decode_envelope(envelope)
    assert decoded["config.json"]["llm_api_key"] == "secret-llm-key"
    assert decoded["oauth_tokens.json"]["r1"]["refresh_token"] == "secret-refresh"


def test_redacted_backup_contains_no_secrets_and_cannot_restore(tmp_data_dir, monkeypatch):
    _seed(tmp_data_dir)
    monkeypatch.setenv("HH_BOT_DISABLE_DATA_ENCRYPTION", "1")
    monkeypatch.delenv("HH_BOT_DATA_KEY", raising=False)
    monkeypatch.setattr("app.routes._API_KEY", "test-key")

    response = client.get("/api/backup", headers={"X-API-Key": "test-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["redacted"] is True
    body = response.text
    for secret in ("secret-llm-key", "secret-cookie", "secret-access", "secret-refresh"):
        assert secret not in body

    restore = client.post("/api/backup", json=payload, headers={"X-API-Key": "test-key"})
    assert restore.status_code == 200
    assert restore.json()["ok"] is False
    assert "Redacted" in restore.json()["error"]


def test_encrypted_backup_restores_with_same_key(tmp_data_dir, monkeypatch):
    _seed(tmp_data_dir)
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "portable-backup-test-key")
    monkeypatch.setattr("app.routes._API_KEY", "test-key")

    backup = client.get("/api/backup", headers={"X-API-Key": "test-key"})
    assert backup.status_code == 200
    assert secure_store.is_secure_envelope(backup.json())

    secure_store.write_json_atomic(tmp_data_dir / "config.json", {"llm_api_key": "changed"})
    restore = client.post(
        "/api/backup", json=backup.json(), headers={"X-API-Key": "test-key"}
    )

    assert restore.status_code == 200
    assert restore.json()["ok"] is True
    restored = secure_store.read_json(tmp_data_dir / "config.json")
    assert restored["llm_api_key"] == "secret-llm-key"
    assert "secret-llm-key" not in (tmp_data_dir / "config.json").read_text(encoding="utf-8")


def test_raw_query_cannot_bypass_encrypted_backup(tmp_data_dir, monkeypatch):
    _seed(tmp_data_dir)
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "raw-bypass-test-key")
    monkeypatch.setattr("app.routes._API_KEY", "test-key")

    response = client.get(
        "/api/backup?raw=1", headers={"X-API-Key": "test-key"}
    )

    assert response.status_code == 200
    assert "secret-llm-key" not in response.text
    assert "secret-cookie" not in response.text
    assert secure_store.is_secure_envelope(response.json())
