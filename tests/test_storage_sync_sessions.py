import json

from app import storage


def test_save_browser_sessions_wait_writes_immediately(monkeypatch, tmp_path):
    target = tmp_path / "browser_sessions.json"
    monkeypatch.setattr(storage, "SESSIONS_FILE", target)
    monkeypatch.setattr(storage, "_sessions_pending_snapshot", None)
    monkeypatch.setattr(storage, "_sessions_pending_seq", 0)
    monkeypatch.setattr(storage, "_sessions_written_seq", 0)

    storage.save_browser_sessions(
        [{"name": "OTP account", "resume_hash": "rh", "cookies": {"hhtoken": "secret"}}],
        wait=True,
    )

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved[0]["name"] == "OTP account"
    assert saved[0]["resume_hash"] == "rh"
