from types import SimpleNamespace

import pytest

import app.llm_provider as provider


def _deepseek(model="deepseek-v4-flash"):
    return {
        "name": "DeepSeek",
        "api_key": "test-key",
        "base_url": "https://api.deepseek.com",
        "model": model,
        "enabled": True,
    }


def test_deepseek_capabilities_and_retired_model_warning():
    profile = _deepseek("deepseek-chat")
    assert provider.provider_name(profile) == "deepseek"
    assert provider.profile_protocol(profile) == "openai_compatible"
    caps = provider.provider_capabilities(profile)
    assert caps.json_object is True
    assert caps.responses_api is True
    assert "retired" in provider.model_warning(profile).lower()
    assert provider.model_warning(_deepseek()) == ""


def test_native_anthropic_protocol_is_not_faked_as_openai():
    profile = {
        "api_key": "test",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-test",
    }
    assert provider.provider_name(profile) == "anthropic"
    assert provider.profile_protocol(profile) == "anthropic"
    assert provider.provider_capabilities(profile).json_schema is True


def test_enabled_profiles_preserves_legacy_compatibility():
    config = SimpleNamespace(
        llm_profiles=[],
        llm_api_key="legacy-key",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-v4-flash",
    )
    profiles = provider.enabled_profiles(config)
    assert len(profiles) == 1
    assert profiles[0]["api_key"] == "legacy-key"
    assert profiles[0]["model"] == "deepseek-v4-flash"


def test_complete_chat_retries_only_retryable_errors(monkeypatch):
    calls = []

    def fake_complete(profile, messages, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise provider.LLMProviderError(
                "busy", kind="rate_limit", retryable=True, status_code=429, provider="deepseek"
            )
        return provider.LLMResult(
            text="ok", provider="deepseek", profile="DeepSeek", model="deepseek-v4-flash",
            protocol="openai_compatible",
        )

    monkeypatch.setattr(provider, "_complete_openai", fake_complete)
    monkeypatch.setattr(provider, "_sleep_backoff", lambda attempt: None)
    result = provider.complete_chat(_deepseek(), [{"role": "user", "content": "hi"}])
    assert result.text == "ok"
    assert result.attempts == 2
    assert len(calls) == 2


def test_complete_chat_does_not_retry_auth_error(monkeypatch):
    calls = []

    def fake_complete(profile, messages, **kwargs):
        calls.append(1)
        raise provider.LLMProviderError(
            "bad key", kind="auth", retryable=False, status_code=401, provider="deepseek"
        )

    monkeypatch.setattr(provider, "_complete_openai", fake_complete)
    monkeypatch.setattr(provider, "_sleep_backoff", lambda attempt: pytest.fail("must not back off"))
    with pytest.raises(provider.LLMProviderError) as exc:
        provider.complete_chat(_deepseek(), [{"role": "user", "content": "hi"}])
    assert exc.value.kind == "auth"
    assert len(calls) == 1


def test_status_classification_matches_provider_retry_policy():
    assert provider._status_error(429, "rate", "deepseek").retryable is True
    assert provider._status_error(503, "busy", "deepseek").retryable is True
    assert provider._status_error(401, "bad", "deepseek").retryable is False
    assert provider._status_error(402, "balance", "deepseek").kind == "billing"
    assert provider._status_error(422, "bad params", "deepseek").kind == "invalid_request"


def test_native_anthropic_maps_internal_json_schema_to_output_config(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        headers = {"request-id": "req-123"}
        text = ""

        @staticmethod
        def json():
            return {
                "content": [{"type": "text", "text": '{"answer":"ok"}'}],
                "usage": {"input_tokens": 10, "output_tokens": 4},
            }

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            captured["url"] = url
            captured["request"] = kwargs
            return FakeResponse()

    monkeypatch.setattr(provider.httpx, "Client", FakeClient)
    profile = {
        "name": "Claude",
        "api_key": "test-key",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-opus-5",
        "protocol": "anthropic",
    }
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    result = provider.complete_chat(
        profile,
        [{"role": "system", "content": "Return JSON"}, {"role": "user", "content": "hi"}],
        response_format={"type": "json_schema", "json_schema": {"name": "x", "strict": True, "schema": schema}},
        max_attempts=1,
    )
    assert result.text == '{"answer":"ok"}'
    assert result.request_id == "req-123"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["request"]["json"]["output_config"] == {
        "format": {"type": "json_schema", "schema": schema}
    }
