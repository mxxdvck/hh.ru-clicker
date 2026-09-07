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
        self.applied_calls = []

    def toggle_pause(self):
        self.paused = not self.paused

    def toggle_account_pause(self, idx):
        state = self.account_states[idx]
        state.paused = not state.paused
        state.paused_reason = "manual" if state.paused else ""

    def apply_search_results(self, idx, vacancy_ids=None):
        state = self.account_states[idx]
        queue = [str(value) for value in state.vacancies_queue]
        requested = [str(value) for value in (vacancy_ids or [])]
        if not state.paused or state.paused_reason != "search_only" or not requested:
            return False
        if any(value not in queue for value in requested):
            return False
        self.applied_calls.append((idx, requested))
        state.paused = False
        state.paused_reason = ""
        state.status = "applying"
        return True


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


def _last_text(session):
    return session.calls[-1][1]["text"]


def _confirmation_token(text):
    tail = text.split("/confirm ", 1)[1]
    return tail.split()[0]


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
    text = _last_text(session)
    assert "#0 one: applying" in text
    assert "#1 two: paused · manual" in text
    assert "⛔" in text


def test_global_pause_requires_one_time_confirmation():
    bot = _Bot()
    session = _Session()
    remote = TelegramRemote(bot, "123:secret", {100}, session=session)

    remote.process_update(_update(text="/pause"))
    assert bot.paused is False
    token = _confirmation_token(_last_text(session))

    remote.process_update(_update(text=f"/confirm {token}"))
    assert bot.paused is True
    assert "✅" in _last_text(session)

    remote.process_update(_update(text=f"/confirm {token}"))
    assert bot.paused is True
    assert "Нет ожидающего действия" in _last_text(session)


def test_wrong_confirmation_code_does_not_mutate():
    bot = _Bot()
    session = _Session()
    remote = TelegramRemote(bot, "123:secret", {100}, session=session)
    remote.process_update(_update(text="/pause"))

    remote.process_update(_update(text="/confirm deadbeef"))
    assert bot.paused is False
    assert "Неверный код" in _last_text(session)


def test_account_confirmation_is_target_state_not_blind_toggle():
    bot = _Bot()
    state = _state(short="one")
    bot.account_states = [state]
    session = _Session()
    remote = TelegramRemote(bot, "123:secret", {100}, session=session)

    remote.process_update(_update(text="/account 0 pause"))
    token = _confirmation_token(_last_text(session))
    # Simulate dashboard changing the state before Telegram confirmation arrives.
    state.paused = True
    state.paused_reason = "manual"
    remote.process_update(_update(text=f"/confirm {token}"))

    assert state.paused is True
    assert "повторный toggle не нужен" in _last_text(session)


def test_apply_queue_captures_exact_ids_and_uses_existing_safe_flow(monkeypatch):
    from app.config import CONFIG

    monkeypatch.setattr(CONFIG, "search_only_mode", True)
    bot = _Bot()
    state = _state(
        short="one",
        status="search_only",
        paused=True,
        paused_reason="search_only",
        vacancies_queue=["11", "22", "33"],
    )
    bot.account_states = [state]
    session = _Session()
    remote = TelegramRemote(bot, "123:secret", {100}, session=session)

    remote.process_update(_update(text="/apply_queue 0"))
    token = _confirmation_token(_last_text(session))
    remote.process_update(_update(text=f"/confirm {token}"))

    assert bot.applied_calls == [(0, ["11", "22", "33"])]
    assert state.status == "applying"


def test_apply_subset_rejects_id_outside_current_safe_queue(monkeypatch):
    from app.config import CONFIG

    monkeypatch.setattr(CONFIG, "search_only_mode", True)
    bot = _Bot()
    bot.account_states = [
        _state(paused=True, paused_reason="search_only", vacancies_queue=["11", "22"])
    ]
    session = _Session()
    remote = TelegramRemote(bot, "123:secret", {100}, session=session)

    remote.process_update(_update(text="/apply 0 11 999"))
    assert bot.applied_calls == []
    assert "999" in _last_text(session)
    assert "/confirm" not in _last_text(session)


def test_apply_confirmation_fails_if_queue_changed(monkeypatch):
    from app.config import CONFIG

    monkeypatch.setattr(CONFIG, "search_only_mode", True)
    bot = _Bot()
    state = _state(paused=True, paused_reason="search_only", vacancies_queue=["11", "22"])
    bot.account_states = [state]
    session = _Session()
    remote = TelegramRemote(bot, "123:secret", {100}, session=session)

    remote.process_update(_update(text="/apply_queue 0"))
    token = _confirmation_token(_last_text(session))
    state.vacancies_queue = ["11"]
    remote.process_update(_update(text=f"/confirm {token}"))

    assert bot.applied_calls == []
    assert "отклонено сервером" in _last_text(session)


def test_cancel_consumes_pending_action():
    bot = _Bot()
    session = _Session()
    remote = TelegramRemote(bot, "123:secret", {100}, session=session)
    remote.process_update(_update(text="/pause"))
    token = _confirmation_token(_last_text(session))

    remote.process_update(_update(text="/cancel"))
    remote.process_update(_update(text=f"/confirm {token}"))
    assert bot.paused is False
    assert "Нет ожидающего действия" in _last_text(session)


def test_unknown_command_does_not_expose_configuration():
    session = _Session()
    remote = TelegramRemote(_Bot(), "123:super-secret-token", {100}, session=session)
    assert remote.process_update(_update(text="/something")) is True
    text = _last_text(session)
    assert "super-secret-token" not in text
    assert "Неизвестная команда" in text


def test_module_does_not_read_token_from_generic_environment_name(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999:wrong")
    monkeypatch.setenv("HH_BOT_TELEGRAM_ENABLED", "1")
    monkeypatch.delenv("HH_BOT_TELEGRAM_TOKEN", raising=False)
    monkeypatch.setenv("HH_BOT_TELEGRAM_ALLOWED_CHAT_IDS", "100")
    assert TelegramRemote.from_env(_Bot()) is None
