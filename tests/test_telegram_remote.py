import os
import threading
from types import SimpleNamespace

from app.telegram_remote import TelegramRemote, _parse_allowed_chat_ids


class _Response:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class _Session:
    def __init__(self):
        self.calls = []
        self.closed = False

    def post(self, url, data=None, timeout=None):
        self.calls.append((url, dict(data or {}), timeout))
        return _Response({"ok": True, "result": True})

    def close(self):
        self.closed = True


class _Bot:
    def __init__(self):
        self.paused = False
        self.account_states = []
        self.temp_states = {}


def _state(**overrides):
    values = {
        "short": "acc",
        "status": "idle",
        "status_detail": "",
        "paused": False,
        "paused_reason": "",
        "hard_stopped": False,
        "daily_sent": 2,
        "sent": 1,
        "found_vacancies": 10,
        "vacancies_queue": ["1", "2"],
        "llm_pending_chats": 0,
        "_state_lock": threading.Lock(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _update(chat_id=100, *, chat_type="private", text="/status"):
    return {
        "update_id": 10,
        "message": {
            "chat": {"id": chat_id, "type": chat_type},
            "text": text,
        },
    }


def test_parse_allowed_chat_ids_is_strict_and_deduplicates():
    assert _parse_allowed_chat_ids("100, 200,100") == frozenset({100, 200})
    for raw in ("100,nope", "-100123", "0"):
        try:
            _parse_allowed_chat_ids(raw)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid allowlist for {raw!r}")


def test_from_env_is_opt_in_and_fail_closed(monkeypatch):
    bot = _Bot()
    for key in (
        "HH_BOT_TELEGRAM_ENABLED",
        "HH_BOT_TELEGRAM_TOKEN",
        "HH_BOT_TELEGRAM_ALLOWED_CHAT_IDS",
    ):
        monkeypatch.delenv(key, raising=False)
    assert TelegramRemote.from_env(bot) is None

    monkeypatch.setenv("HH_BOT_TELEGRAM_ENABLED", "1")
    monkeypatch.setenv("HH_BOT_TELEGRAM_TOKEN", "123:secret")
    assert TelegramRemote.from_env(bot) is None

    monkeypatch.setenv("HH_BOT_TELEGRAM_ALLOWED_CHAT_IDS", "100")
    remote = TelegramRemote.from_env(bot)
    assert isinstance(remote, TelegramRemote)
    remote.stop()


def test_unauthorized_and_group_messages_are_silent():
    session = _Session()
    remote = TelegramRemote(_Bot(), "123:secret", {100}, session=session)

    assert remote.process_update(_update(chat_id=999)) is False
    assert remote.process_update(_update(chat_id=100, chat_type="group")) is False
    assert session.calls == []


def test_status_command_replies_without_mutating_bot():
    bot = _Bot()
    bot.account_states = [_state(short="main", status="search_only", paused=True, paused_reason="search_only")]
    session = _Session()
    remote = TelegramRemote(bot, "123:secret", {100}, session=session)

    assert remote.process_update(_update(text="/status")) is True
    assert bot.paused is False
    assert bot.account_states[0].paused is True
    assert len(session.calls) == 1
    url, payload, _ = session.calls[0]
    assert url.endswith("/sendMessage")
    assert payload["chat_id"] == 100
    assert "Аккаунтов: 1" in payload["text"]
    assert "на паузе: 1" in payload["text"]


def test_accounts_command_includes_safe_runtime_summary():
    bot = _Bot()
    bot.account_states = [
        _state(short="one", status="applying", daily_sent=3, sent=2),
        _state(short="two", status="paused", paused=True, paused_reason="manual", hard_stopped=True),
    ]
    session = _Session()
    remote = TelegramRemote(bot, "123:secret", {100}, session=session)

    assert remote.process_update(_update(text="/accounts")) is True
    text = session.calls[0][1]["text"]
    assert "#0 one: applying" in text
    assert "#1 two: paused · manual" in text
    assert "⛔" in text


def test_unknown_command_does_not_expose_configuration():
    session = _Session()
    remote = TelegramRemote(_Bot(), "123:super-secret-token", {100}, session=session)
    assert remote.process_update(_update(text="/something")) is True
    text = session.calls[0][1]["text"]
    assert "super-secret-token" not in text
    assert "Неизвестная команда" in text


def test_module_does_not_read_token_from_generic_environment_name(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999:wrong")
    monkeypatch.setenv("HH_BOT_TELEGRAM_ENABLED", "1")
    monkeypatch.delenv("HH_BOT_TELEGRAM_TOKEN", raising=False)
    monkeypatch.setenv("HH_BOT_TELEGRAM_ALLOWED_CHAT_IDS", "100")
    assert TelegramRemote.from_env(_Bot()) is None
