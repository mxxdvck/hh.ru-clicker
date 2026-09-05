from app.logging_utils import redact_sensitive_text


def test_redacts_bearer_tokens_and_keys():
    fake_key = "sk-" + ("x" * 24)
    text = f"Authorization: Bearer abcdef123456 access_token=tok123456 api_key={fake_key}"
    out = redact_sensitive_text(text)
    assert "abcdef123456" not in out
    assert "tok123456" not in out
    assert fake_key not in out
    assert "[REDACTED]" in out


def test_redacts_cookie_and_proxy_password():
    text = "hhtoken=cookie123; _xsrf=xsrf123 proxy=https://user:pass@example.com"
    out = redact_sensitive_text(text)
    assert "cookie123" not in out
    assert "xsrf123" not in out
    assert "user:pass@" not in out
