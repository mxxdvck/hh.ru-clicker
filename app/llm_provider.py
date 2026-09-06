"""Provider-neutral LLM transport used by Phase 4.

The rest of the application should not know how API keys, retries, protocol
headers, request IDs, or token usage are implemented by each provider.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import random
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.logging_utils import log_debug

try:
    import openai as _openai
except ImportError:  # pragma: no cover
    _openai = None


_DEEPSEEK_RETIRED_MODELS = {"deepseek-chat", "deepseek-reasoner"}
_GEMINI_RETIRED_MODELS = {"gemini-2.0-flash", "gemini-2.0-flash-001", "gemini-2.0-flash-lite", "gemini-2.0-flash-lite-001"}
_GROQ_DEVELOPER_REPLACEMENTS = {
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
}
_GROQ_JSON_SCHEMA_MODELS = {"openai/gpt-oss-120b", "openai/gpt-oss-20b"}
_TRANSIENT_HTTP = {408, 409, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class LLMCapabilities:
    json_object: bool = False
    json_schema: bool = False
    responses_api: bool = False


@dataclass
class LLMResult:
    text: str
    provider: str
    profile: str
    model: str
    protocol: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    request_id: str = ""
    latency_ms: int = 0
    attempts: int = 1


class LLMProviderError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "provider_error", retryable: bool = False,
                 status_code: int | None = None, provider: str = ""):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.status_code = status_code
        self.provider = provider


def _profile_base_url(profile: dict) -> str:
    return str(profile.get("base_url") or "https://api.openai.com/v1").rstrip("/")


def provider_name(profile: dict) -> str:
    host = (urlparse(_profile_base_url(profile)).hostname or "").lower()
    if host == "api.deepseek.com":
        return "deepseek"
    if host == "api.openai.com":
        return "openai"
    if host == "api.anthropic.com":
        return "anthropic"
    if "generativelanguage.googleapis.com" in host:
        return "gemini"
    if host == "openrouter.ai":
        return "openrouter"
    if host == "api.groq.com":
        return "groq"
    if host == "api.mistral.ai":
        return "mistral"
    if host == "api.together.xyz":
        return "together"
    return host or "custom"


def profile_name(profile: dict) -> str:
    return str(profile.get("name") or profile.get("model") or provider_name(profile) or "LLM").strip()


def profile_protocol(profile: dict) -> str:
    explicit = str(profile.get("protocol") or "").strip().lower()
    if explicit in {"openai", "openai_compatible"}:
        return "openai_compatible"
    if explicit == "anthropic":
        return "anthropic"
    if explicit:
        raise LLMProviderError(f"Unsupported LLM protocol: {explicit}", kind="unsupported_protocol",
                               provider=provider_name(profile))
    return "anthropic" if provider_name(profile) == "anthropic" else "openai_compatible"


def provider_capabilities(profile: dict) -> LLMCapabilities:
    provider = provider_name(profile)
    protocol = profile_protocol(profile)
    if protocol == "anthropic":
        return LLMCapabilities(json_schema=True)
    if provider == "openai":
        return LLMCapabilities(json_object=True, json_schema=True, responses_api=True)
    if provider == "deepseek":
        return LLMCapabilities(json_object=True, json_schema=False, responses_api=True)
    if provider == "gemini":
        return LLMCapabilities(json_object=True, json_schema=True)
    if provider == "groq":
        model = str(profile.get("model") or "").strip().lower()
        return LLMCapabilities(
            json_object=True,
            json_schema=model in _GROQ_JSON_SCHEMA_MODELS,
        )
    return LLMCapabilities(json_object=True, json_schema=False)


def model_warning(profile: dict) -> str:
    model = str(profile.get("model") or "").strip()
    provider = provider_name(profile)
    if provider == "deepseek" and model in _DEEPSEEK_RETIRED_MODELS:
        return (f"DeepSeek model '{model}' is retired. Use 'deepseek-v4-flash' for routine replies "
                "or 'deepseek-v4-pro' for higher quality.")
    if provider == "gemini" and model in _GEMINI_RETIRED_MODELS:
        return f"Gemini model '{model}' is retired. Use 'gemini-3.8-flash'."
    if provider == "groq" and model in _GROQ_DEVELOPER_REPLACEMENTS:
        replacement = _GROQ_DEVELOPER_REPLACEMENTS[model]
        return (f"Groq model '{model}' may require Enterprise access. "
                f"Use '{replacement}' for Developer Plan compatibility.")
    return ""


def enabled_profiles(config: Any) -> list[dict]:
    profiles = [dict(p) for p in (getattr(config, "llm_profiles", None) or [])
                if isinstance(p, dict) and p.get("enabled", True) and p.get("api_key")]
    if profiles:
        return profiles
    api_key = str(getattr(config, "llm_api_key", "") or "").strip()
    if not api_key:
        return []
    return [{"name": "legacy", "api_key": api_key, "base_url": getattr(config, "llm_base_url", ""),
             "model": getattr(config, "llm_model", ""), "protocol": "openai_compatible", "enabled": True}]


def _proxy_client(timeout_seconds: float) -> httpx.Client | None:
    proxy = os.environ.get("LLM_PROXY", "").strip()
    if not proxy:
        return None
    try:
        return httpx.Client(proxy=proxy, timeout=timeout_seconds)
    except TypeError:  # pragma: no cover
        return httpx.Client(proxies=proxy, timeout=timeout_seconds)


def _openai_client(profile: dict, timeout_seconds: float):
    if _openai is None:
        raise LLMProviderError("openai package is not installed", kind="dependency_missing")
    kwargs = {"api_key": profile.get("api_key"), "base_url": _profile_base_url(profile), "timeout": timeout_seconds}
    proxy_client = _proxy_client(timeout_seconds)
    if proxy_client is not None:
        kwargs["http_client"] = proxy_client
    return _openai.OpenAI(**kwargs)


def _status_error(status: int, text: str, provider: str) -> LLMProviderError:
    if status in {401, 403}:
        kind = "auth"
    elif status == 402:
        kind = "billing"
    elif status == 422:
        kind = "invalid_request"
    elif status == 429:
        kind = "rate_limit"
    elif status >= 500:
        kind = "server"
    else:
        kind = "http_error"
    return LLMProviderError(f"{provider} HTTP {status}: {text[:240]}", kind=kind,
                            retryable=status in _TRANSIENT_HTTP, status_code=status, provider=provider)


def _classify_exception(exc: Exception, provider: str) -> LLMProviderError:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return _status_error(status, str(exc), provider)
    name = type(exc).__name__.lower()
    text = str(exc)
    if "timeout" in name or "timeout" in text.lower():
        return LLMProviderError(text or "LLM timeout", kind="timeout", retryable=True, provider=provider)
    if "connection" in name or "connect" in text.lower():
        return LLMProviderError(text or "LLM connection error", kind="connection", retryable=True, provider=provider)
    return LLMProviderError(text or type(exc).__name__, kind="provider_error", provider=provider)


def _sleep_backoff(attempt: int) -> None:
    delay = min(4.0, 0.45 * (2 ** max(0, attempt - 1))) + random.uniform(0.0, 0.25)
    time.sleep(delay)


def _complete_openai(profile: dict, messages: list[dict], *, max_tokens: int, temperature: float,
                     response_format: dict | None, timeout_seconds: float) -> LLMResult:
    provider = provider_name(profile)
    model = str(profile.get("model") or "").strip()
    if not model:
        raise LLMProviderError("LLM model is empty", kind="invalid_config", provider=provider)
    client = _openai_client(profile, timeout_seconds)
    kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if response_format:
        kwargs["response_format"] = response_format
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(**kwargs)
        latency_ms = int((time.perf_counter() - started) * 1000)
        choices = getattr(response, "choices", None) or []
        text = str(getattr(choices[0].message, "content", "") or "").strip() if choices else ""
        usage = getattr(response, "usage", None)
        return LLMResult(text=text, provider=provider, profile=profile_name(profile), model=model,
                         protocol="openai_compatible",
                         prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
                         completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
                         request_id=str(getattr(response, "_request_id", "") or ""), latency_ms=latency_ms)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _anthropic_uses_fixed_sampling(model: str) -> bool:
    """Claude 4.7+ and Mythos reject non-default legacy sampling parameters."""
    normalized = str(model or "").strip().lower()
    if normalized.startswith("claude-mythos"):
        return True
    match = re.match(r"^claude-[a-z0-9]+-(\d+)(?:-(\d+))?", normalized)
    if not match:
        return False
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    return major >= 5 or (major == 4 and minor >= 7)


def _merge_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts: list[str] = []
    converted: list[dict] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        role = "assistant" if role == "assistant" else "user"
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"] += "\n\n" + content
        else:
            converted.append({"role": role, "content": content})
    return "\n\n".join(system_parts), converted


def _complete_anthropic(profile: dict, messages: list[dict], *, max_tokens: int,
                        temperature: float, response_format: dict | None,
                        timeout_seconds: float) -> LLMResult:
    provider = provider_name(profile)
    model = str(profile.get("model") or "").strip()
    if not model:
        raise LLMProviderError("LLM model is empty", kind="invalid_config", provider=provider)
    system, converted = _merge_anthropic_messages(messages)
    headers = {"x-api-key": str(profile.get("api_key") or ""), "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    payload: dict[str, Any] = {"model": model, "messages": converted, "max_tokens": max_tokens}
    if not _anthropic_uses_fixed_sampling(model):
        payload["temperature"] = temperature
    if system:
        payload["system"] = system
    if response_format:
        fmt_type = str(response_format.get("type") or "")
        if fmt_type != "json_schema":
            raise LLMProviderError(
                f"Anthropic protocol requires json_schema for structured output, got {fmt_type or 'unknown'}",
                kind="unsupported_capability", provider=provider,
            )
        schema_block = response_format.get("json_schema") or {}
        schema = schema_block.get("schema") if isinstance(schema_block, dict) else None
        if not isinstance(schema, dict):
            raise LLMProviderError("Anthropic json_schema is missing schema",
                                   kind="invalid_request", provider=provider)
        payload["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    proxy = os.environ.get("LLM_PROXY", "").strip() or None
    started = time.perf_counter()
    with httpx.Client(proxy=proxy, timeout=timeout_seconds) as client:
        response = client.post(f"{_profile_base_url(profile)}/messages", headers=headers, json=payload)
    latency_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        raise _status_error(response.status_code, response.text, provider)
    data = response.json()
    text = "".join(str(block.get("text") or "") for block in (data.get("content") or [])
                   if isinstance(block, dict) and block.get("type") == "text").strip()
    usage = data.get("usage") or {}
    return LLMResult(text=text, provider=provider, profile=profile_name(profile), model=model,
                     protocol="anthropic", prompt_tokens=usage.get("input_tokens"),
                     completion_tokens=usage.get("output_tokens"),
                     request_id=response.headers.get("request-id", "") or response.headers.get("x-request-id", ""),
                     latency_ms=latency_ms)


def complete_chat(profile: dict, messages: list[dict], *, max_tokens: int = 300, temperature: float = 0.3,
                  response_format: dict | None = None, timeout_seconds: float = 60.0,
                  max_attempts: int = 3) -> LLMResult:
    """Complete a chat request with bounded retries and normalized telemetry."""
    protocol = profile_protocol(profile)
    provider = provider_name(profile)
    attempts = max(1, min(int(max_attempts or 1), 4))
    last_error: LLMProviderError | None = None
    for attempt in range(1, attempts + 1):
        try:
            if protocol == "anthropic":
                result = _complete_anthropic(
                    profile, messages, max_tokens=max_tokens, temperature=temperature,
                    response_format=response_format, timeout_seconds=timeout_seconds,
                )
            else:
                result = _complete_openai(profile, messages, max_tokens=max_tokens, temperature=temperature,
                                          response_format=response_format, timeout_seconds=timeout_seconds)
            result.attempts = attempt
            return result
        except LLMProviderError as exc:
            last_error = exc
        except Exception as exc:
            last_error = _classify_exception(exc, provider)
        log_debug(f"LLM provider error provider={provider} kind={last_error.kind} "
                  f"attempt={attempt}/{attempts} retryable={last_error.retryable}")
        if not last_error.retryable or attempt >= attempts:
            raise last_error
        _sleep_backoff(attempt)
    raise last_error or LLMProviderError("LLM request failed", provider=provider)
