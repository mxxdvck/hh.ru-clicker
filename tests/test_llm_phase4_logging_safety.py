from pathlib import Path
from types import SimpleNamespace
import subprocess

from app import llm
import app.llm_provider as llm_provider
from app.config import CONFIG


def _profile():
    return {
        "name": "Test",
        "api_key": "test",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "enabled": True,
    }


def test_invalid_structured_reply_is_not_exposed_as_review_draft(monkeypatch):
    secret = "SECRET_TOKEN_INVALID_JSON_abcdefghijklmnop"
    monkeypatch.setattr(CONFIG, "llm_profile_mode", "fallback")
    monkeypatch.setattr(llm, "_enabled_profiles", lambda _config: [_profile()])
    monkeypatch.setattr(
        llm, "_complete_chat",
        lambda *args, **kwargs: SimpleNamespace(
            text=secret, provider="deepseek", model="deepseek-v4-flash",
            latency_ms=1, attempts=1, request_id="",
        ),
    )

    decision = llm.generate_llm_reply_decision(
        [{"sender": "employer", "text": "Are you interested?"}],
        account_key="privacy-invalid-json",
    )

    assert decision.answer == ""
    assert decision.action == "skip"
    assert secret not in str(llm.get_llm_last_status("privacy-invalid-json", "reply"))


def test_provider_error_body_is_not_logged_or_exposed(monkeypatch):
    secret = "SECRET_PROVIDER_BODY_abcdefghijklmnop"
    logs = []

    class ProviderBoom(RuntimeError):
        kind = "server"
        status_code = 500
        provider = "deepseek"

    monkeypatch.setattr(CONFIG, "llm_profile_mode", "fallback")
    monkeypatch.setattr(llm, "_enabled_profiles", lambda _config: [_profile()])
    monkeypatch.setattr(llm, "_complete_chat", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderBoom(secret)))
    monkeypatch.setattr(llm, "log_debug", logs.append)

    decision = llm.generate_llm_reply_decision(
        [{"sender": "employer", "text": "Hello?"}],
        account_key="privacy-provider-error",
    )

    assert decision.action == "skip"
    assert secret not in "\n".join(logs)
    assert secret not in str(llm.get_llm_last_status("privacy-provider-error", "reply"))


def test_openclaw_error_output_is_redacted_from_status_and_logs(monkeypatch):
    secret = "SECRET_OPENCLAW_OUTPUT"
    logs = []
    monkeypatch.setattr(CONFIG, "llm_openclaw_agent", "main")
    monkeypatch.setattr(CONFIG, "llm_openclaw_model", "")
    monkeypatch.setattr(CONFIG, "llm_openclaw_timeout", 30)
    monkeypatch.setattr(llm, "_openclaw_command", lambda: ["openclaw"])
    monkeypatch.setattr(llm, "log_debug", logs.append)
    monkeypatch.setattr(
        llm.subprocess, "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 1, stdout=secret, stderr=secret + " stderr",
        ),
    )

    result = llm._run_openclaw_prompt("sensitive prompt", "privacy-openclaw", "reply")

    assert result == ""
    assert secret not in "\n".join(logs)
    assert secret not in str(llm.get_llm_last_status("privacy-openclaw", "reply"))

def test_robot_debug_does_not_log_button_texts():
    source = (Path(__file__).parents[1] / "app/manager.py").read_text(encoding="utf-8")
    assert "buttons={[b.get('text') for b in _text_buttons]}" not in source
    assert "robot decision; buttons={len(_text_buttons)}" in source

def test_provider_http_error_never_embeds_response_body():
    secret = "SECRET_RESPONSE_BODY_abcdefghijklmnop"
    exc = llm_provider._status_error(500, secret, "anthropic")
    assert secret not in str(exc)
    assert "response_chars=" in str(exc)
    assert exc.status_code == 500

def test_manager_activity_log_does_not_embed_reply_snippets():
    source = (Path(__file__).parents[1] / "app/manager.py").read_text(encoding="utf-8")
    assert "reply_text[:60]" not in source
