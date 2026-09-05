from app import secure_store
from scripts import mobile_smoke_test, oauth_status_check, rotate_oauth_tokens
from scripts.migrate_sessions_dedup_by_user import migrate


def _enable_aes(monkeypatch):
    monkeypatch.delenv("HH_BOT_DISABLE_DATA_ENCRYPTION", raising=False)
    monkeypatch.setenv("HH_BOT_DATA_KEY", "script-compat-test-key")


def test_mobile_smoke_reads_encrypted_tokens(tmp_path, monkeypatch):
    _enable_aes(monkeypatch)
    path = tmp_path / "oauth_tokens.json"
    secure_store.write_json_atomic(path, {
        "r1": {"access_token": "a", "refresh_token": "r", "expires_at": 9999999999}
    })
    monkeypatch.setattr(mobile_smoke_test, "TOKENS_PATH", path)

    tokens, error = mobile_smoke_test.load_tokens()

    assert error == ""
    assert tokens["r1"]["access_token"] == "a"


def test_rotate_script_reads_encrypted_tokens(tmp_path, monkeypatch):
    _enable_aes(monkeypatch)
    path = tmp_path / "oauth_tokens.json"
    secure_store.write_json_atomic(path, {"r1": {"expires_at": 9999999999}})
    monkeypatch.setattr(rotate_oauth_tokens, "OAUTH_FILE", path)

    data, status, message = rotate_oauth_tokens.load_tokens()

    assert status == "ok"
    assert message is None
    assert "r1" in data


def test_oauth_status_reads_encrypted_accounts(tmp_path, monkeypatch):
    _enable_aes(monkeypatch)
    path = tmp_path / "accounts.json"
    secure_store.write_json_atomic(path, [{"name": "demo", "resume_hash": "r1"}])
    monkeypatch.setattr(oauth_status_check, "ACCOUNTS_FILE", path)

    accounts = oauth_status_check.load_accounts()

    assert accounts[0]["resume_hash"] == "r1"


def test_session_migration_reads_and_rewrites_encrypted_file(tmp_path, monkeypatch):
    _enable_aes(monkeypatch)
    path = tmp_path / "browser_sessions.json"
    rows = [
        {"user_id": "u1", "resume_hash": "r1", "all_resumes": [{"hash": "r1"}]},
        {"user_id": "u1", "resume_hash": "r2", "all_resumes": [{"hash": "r2"}]},
    ]
    secure_store.write_json_atomic(path, rows)

    result = migrate(path, apply=True)

    assert result["removed"] == 1
    merged = secure_store.read_json(path)
    assert len(merged) == 1
    assert {x["hash"] for x in merged[0]["all_resumes"]} == {"r1", "r2"}
    assert secure_store.is_secure_envelope(__import__("json").loads(path.read_text(encoding="utf-8")))


def test_session_backup_does_not_copy_legacy_plaintext_secret(tmp_path, monkeypatch):
    _enable_aes(monkeypatch)
    from app.session_migration import backup_file

    source = tmp_path / "browser_sessions.json"
    source.write_text('[{"cookies":{"hhtoken":"legacy-cookie"}}]', encoding="utf-8")

    backup = backup_file(source)

    raw = backup.read_text(encoding="utf-8")
    assert "legacy-cookie" not in raw
    assert secure_store.is_secure_envelope(__import__("json").loads(raw))
    assert secure_store.read_json(backup)[0]["cookies"]["hhtoken"] == "legacy-cookie"
