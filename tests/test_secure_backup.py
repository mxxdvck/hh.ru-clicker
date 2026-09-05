import json
import threading

from fastapi.testclient import TestClient

from app.routes import app
from app.routes import settings as settings_routes
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



def test_restore_requires_secure_backend(tmp_data_dir, monkeypatch):
    _seed(tmp_data_dir)
    monkeypatch.setenv("HH_BOT_DISABLE_DATA_ENCRYPTION", "1")
    monkeypatch.delenv("HH_BOT_DATA_KEY", raising=False)
    monkeypatch.setattr("app.routes._API_KEY", "test-key")

    response = client.post(
        "/api/backup",
        json={"config.json": {"llm_api_key": "incoming-secret"}},
        headers={"X-API-Key": "test-key"},
    )

    payload = response.json()
    assert payload["ok"] is False
    assert "Secure storage is unavailable" in payload["error"]
    current = json.loads((tmp_data_dir / "config.json").read_text(encoding="utf-8"))
    assert current["llm_api_key"] == "secret-llm-key"


def test_restore_rolls_back_all_files_on_write_failure(tmp_data_dir, monkeypatch):
    _seed(tmp_data_dir)
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "rollback-test-key")
    monkeypatch.setattr("app.routes._API_KEY", "test-key")

    real_write = settings_routes.secure_write_json
    failed = {"done": False}

    def fail_accounts_once(path, data, *, encrypt=True):
        if path.name == "accounts.json" and not failed["done"]:
            failed["done"] = True
            raise OSError("simulated restore write failure")
        return real_write(path, data, encrypt=encrypt)

    monkeypatch.setattr(settings_routes, "secure_write_json", fail_accounts_once)
    response = client.post(
        "/api/backup",
        json={
            "config.json": {"llm_api_key": "new-secret"},
            "accounts.json": [{"name": "new", "cookies": {"hhtoken": "new-cookie"}}],
        },
        headers={"X-API-Key": "test-key"},
    )

    payload = response.json()
    assert payload["ok"] is False
    assert payload["rolled_back"] is True
    assert payload["rollback_errors"] == {}
    assert payload["restored"] == []
    config = secure_store.read_json(tmp_data_dir / "config.json")
    accounts = secure_store.read_json(tmp_data_dir / "accounts.json")
    assert config["llm_api_key"] == "secret-llm-key"
    assert accounts[0]["cookies"]["hhtoken"] == "secret-cookie"


def test_config_saves_use_shared_persistence_queue():
    from app import config as app_config

    assert app_config._schedule_save is not None
    assert app_config._schedule_save.__module__ == "app.storage"


def test_restore_drains_pending_writes_before_transaction(tmp_data_dir, monkeypatch):
    from app import storage

    _seed(tmp_data_dir)
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "pending-write-test-key")
    monkeypatch.setattr("app.routes._API_KEY", "test-key")

    release = threading.Event()

    def stale_write():
        release.wait(timeout=2)
        secure_store.write_json_atomic(
            tmp_data_dir / "config.json", {"llm_api_key": "stale-pending-secret"}, encrypt=True
        )

    storage._schedule_save(stale_write)
    timer = threading.Timer(0.1, release.set)
    timer.start()
    try:
        response = client.post(
            "/api/backup",
            json={"config.json": {"llm_api_key": "restored-secret"}},
            headers={"X-API-Key": "test-key"},
        )
    finally:
        release.set()
        timer.cancel()

    assert response.json()["ok"] is True
    storage.wait_for_pending_saves()
    config = secure_store.read_json(tmp_data_dir / "config.json")
    assert config["llm_api_key"] == "restored-secret"


def test_backup_wipe_clears_memory_and_blocks_secret_resurrection(tmp_data_dir, monkeypatch):
    from app import oauth, storage
    from app.config import CONFIG, accounts_data

    _seed(tmp_data_dir)
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "wipe-test-key")
    monkeypatch.setattr("app.routes._API_KEY", "test-key")

    old_accounts = list(accounts_data)
    old_key = CONFIG.llm_api_key
    old_profiles = list(CONFIG.llm_profiles)
    with oauth._oauth_lock:
        old_tokens = dict(oauth._oauth_tokens)
        oauth._oauth_tokens.clear()
        oauth._oauth_tokens["r1"] = {
            "access_token": "secret-memory-access",
            "refresh_token": "secret-memory-refresh",
        }
    CONFIG.llm_api_key = "secret-memory-key"
    CONFIG.llm_profiles = [{"name": "demo", "api_key": "secret-profile-key"}]
    accounts_data[:] = [{"name": "demo", "cookies": {"hhtoken": "secret-memory-cookie"}}]

    def stale_pending_write():
        secure_store.write_json_atomic(
            tmp_data_dir / "config.json", {"llm_api_key": "secret-pending-key"}, encrypt=True
        )

    storage._schedule_save(stale_pending_write)
    try:
        response = client.delete("/api/backup", headers={"X-API-Key": "test-key"})
        assert response.json()["ok"] is True
        storage.wait_for_pending_saves()
        with oauth._oauth_lock:
            assert oauth._oauth_tokens == {}
        for name in ("config.json", "accounts.json", "browser_sessions.json", "oauth_tokens.json"):
            body = (tmp_data_dir / name).read_text(encoding="utf-8")
            assert "secret-" not in body
        assert secure_store.read_json(tmp_data_dir / "accounts.json") == []
        assert secure_store.read_json(tmp_data_dir / "oauth_tokens.json") == {}
    finally:
        accounts_data[:] = old_accounts
        CONFIG.llm_api_key = old_key
        CONFIG.llm_profiles = old_profiles
        with oauth._oauth_lock:
            oauth._oauth_tokens.clear()
            oauth._oauth_tokens.update(old_tokens)


def test_restore_preserves_latest_value_after_pending_write(tmp_data_dir, monkeypatch):
    from app import storage

    _seed(tmp_data_dir)
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "preserve-race-test-key")
    monkeypatch.setattr("app.routes._API_KEY", "test-key")

    release = threading.Event()

    def fresh_pending_write():
        release.wait(timeout=2)
        secure_store.write_json_atomic(
            tmp_data_dir / "config.json",
            {"llm_api_key": "fresh-pending-secret", "llm_profiles": []},
            encrypt=True,
        )

    storage._schedule_save(fresh_pending_write)
    timer = threading.Timer(0.1, release.set)
    timer.start()
    try:
        response = client.post(
            "/api/backup",
            json={"config.json": {"llm_api_key": "", "llm_profiles": []}},
            headers={"X-API-Key": "test-key"},
        )
    finally:
        release.set()
        timer.cancel()

    payload = response.json()
    assert payload["ok"] is True
    assert "config.json/llm_api_key" in payload["preserved"]
    config = secure_store.read_json(tmp_data_dir / "config.json")
    assert config["llm_api_key"] == "fresh-pending-secret"

def test_backup_download_drains_pending_writes(tmp_data_dir, monkeypatch):
    from app import storage

    _seed(tmp_data_dir)
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "backup-race-test-key")
    monkeypatch.setattr("app.routes._API_KEY", "test-key")

    release = threading.Event()

    def fresh_pending_write():
        release.wait(timeout=2)
        secure_store.write_json_atomic(
            tmp_data_dir / "config.json",
            {"llm_api_key": "latest-backup-secret", "llm_profiles": []},
            encrypt=True,
        )

    storage._schedule_save(fresh_pending_write)
    timer = threading.Timer(0.1, release.set)
    timer.start()
    try:
        response = client.get("/api/backup", headers={"X-API-Key": "test-key"})
    finally:
        release.set()
        timer.cancel()

    assert response.status_code == 200
    decoded = secure_store.decode_envelope(response.json())
    assert decoded["config.json"]["llm_api_key"] == "latest-backup-secret"
