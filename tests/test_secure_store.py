import json
import os

import pytest

from app import secure_store


def test_plaintext_mode_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_DISABLE_DATA_ENCRYPTION", "1")
    monkeypatch.delenv("HH_BOT_DATA_KEY", raising=False)
    path = tmp_path / "plain.json"
    value = {"secret": "visible", "n": 3}

    provider = secure_store.write_json_atomic(path, value)

    assert provider == "plaintext"
    assert json.loads(path.read_text(encoding="utf-8")) == value
    assert secure_store.read_json(path) == value


def test_aesgcm_roundtrip_hides_plaintext(tmp_path, monkeypatch):
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "unit-test-master-key")
    path = tmp_path / "secret.json"
    value = {"access_token": "super-secret-token", "nested": {"x": 1}}
    provider = secure_store.write_json_atomic(path, value)
    raw = path.read_text(encoding="utf-8")

    assert provider == "aesgcm"
    assert "super-secret-token" not in raw
    envelope = json.loads(raw)
    assert secure_store.is_secure_envelope(envelope)
    assert secure_store.read_json(path) == value


def test_plaintext_file_migrates_to_encrypted(tmp_path, monkeypatch):
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "migration-key")
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"refresh_token": "legacy-secret"}), encoding="utf-8")

    loaded = secure_store.read_json(path, migrate=True)

    assert loaded["refresh_token"] == "legacy-secret"
    raw = path.read_text(encoding="utf-8")
    assert "legacy-secret" not in raw
    assert secure_store.is_secure_envelope(json.loads(raw))


def test_plaintext_migrates_to_aesgcm(tmp_path, monkeypatch):
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "migration-key")
    path = tmp_path / "legacy.json"
    path.write_text('{"refresh_token":"legacy-secret"}', encoding="utf-8")

    value = secure_store.read_json(path, migrate=True)

    assert value == {"refresh_token": "legacy-secret"}
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert secure_store.is_secure_envelope(raw)
    assert "legacy-secret" not in path.read_text(encoding="utf-8")


def test_required_encryption_fails_without_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_DISABLE_DATA_ENCRYPTION", "1")
    monkeypatch.setenv("HH_BOT_REQUIRE_ENCRYPTION", "1")
    monkeypatch.delenv("HH_BOT_DATA_KEY", raising=False)

    with pytest.raises(secure_store.SecureStoreError):
        secure_store.write_json_atomic(tmp_path / "x.json", {"x": 1}, encrypt=True)


def test_wrong_aes_key_cannot_decrypt(tmp_path, monkeypatch):
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "correct-key")
    path = tmp_path / "secret.json"
    secure_store.write_json_atomic(path, {"secret": "value"})

    monkeypatch.setenv("HH_BOT_DATA_KEY", "wrong-key")
    with pytest.raises(secure_store.SecureStoreError):
        secure_store.read_json(path)


def test_encryption_required_fails_without_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_DISABLE_DATA_ENCRYPTION", "1")
    monkeypatch.setenv("HH_BOT_REQUIRE_ENCRYPTION", "1")
    monkeypatch.delenv("HH_BOT_DATA_KEY", raising=False)

    with pytest.raises(secure_store.SecureStoreError):
        secure_store.write_json_atomic(tmp_path / "blocked.json", {"x": 1})


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_dpapi_roundtrip(tmp_path, monkeypatch):
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.delenv("HH_BOT_DATA_KEY", raising=False)
    monkeypatch.delenv("HH_BOT_REQUIRE_ENCRYPTION", raising=False)
    path = tmp_path / "dpapi.json"
    payload = {"cookies": {"hhtoken": "cookie-value"}}

    assert secure_store.write_json_atomic(path, payload) == "dpapi"
    assert "cookie-value" not in path.read_text(encoding="utf-8")
    assert secure_store.read_json(path) == payload


def test_required_encryption_rejects_plaintext_read(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_DISABLE_DATA_ENCRYPTION", "1")
    monkeypatch.setenv("HH_BOT_REQUIRE_ENCRYPTION", "1")
    path = tmp_path / "plain.json"
    path.write_text('{"x":1}', encoding="utf-8")

    with pytest.raises(secure_store.SecureStoreError):
        secure_store.read_json(path, migrate=True)


def test_wrong_key_cannot_overwrite_existing_encrypted_file(tmp_path, monkeypatch):
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "original-key")
    path = tmp_path / "secret.json"
    secure_store.write_json_atomic(path, {"secret": "original"})
    before = path.read_bytes()

    monkeypatch.setenv("HH_BOT_DATA_KEY", "wrong-key")
    with pytest.raises(secure_store.SecureStoreError):
        secure_store.write_json_atomic(path, {"secret": "replacement"})

    assert path.read_bytes() == before


def test_plaintext_envelope_is_rejected():
    envelope = {
        secure_store.MAGIC: secure_store.VERSION,
        "provider": "plaintext",
        "payload": "eyJ4IjoxfQ==",
    }

    with pytest.raises(secure_store.SecureStoreError):
        secure_store.decode_envelope(envelope)
