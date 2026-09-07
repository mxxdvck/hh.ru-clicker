"""Project Phase 6: secure Telegram remote, read-only foundation.

The remote deliberately starts with observability only. Mutating commands are added
in later Phase 6 slices and must call existing BotManager operations so Telegram
never becomes a second, less-safe application engine.
"""

from __future__ import annotations

from contextlib import nullcontext
import json
import os
import threading
from typing import Any

import requests

from app.config import CONFIG
from app.logging_utils import log_debug


_ENV_ENABLED = "HH_BOT_TELEGRAM_ENABLED"
_ENV_TOKEN = "HH_BOT_TELEGRAM_TOKEN"
_ENV_ALLOWED_CHAT_IDS = "HH_BOT_TELEGRAM_ALLOWED_CHAT_IDS"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUE_VALUES


def _parse_allowed_chat_ids(raw: str) -> frozenset[int]:
    """Parse private Telegram chat ids, rejecting a partially broken allowlist."""
    values: set[int] = set()
    for part in str(raw or "").split(","):
        text = part.strip()
        if not text:
            continue
        try:
            chat_id = int(text)
        except ValueError as exc:
            raise ValueError("invalid Telegram chat id") from exc
        # Private Telegram chat ids are positive. Negative ids are groups/channels;
        # Phase 6 intentionally refuses those because any group member could issue commands.
        if chat_id <= 0:
            raise ValueError("Telegram remote accepts private chat ids only")
        values.add(chat_id)
    return frozenset(values)


def _effective_daily_limit() -> int:
    limits = []
    for raw in (getattr(CONFIG, "daily_apply_limit", 0), getattr(CONFIG, "hh_daily_limit", 0)):
        try:
            value = int(raw or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            limits.append(value)
    return min(limits) if limits else 0


class TelegramRemote:
    """Small Bot API long-polling client with an explicit private-chat allowlist."""

    def __init__(
        self,
        bot: Any,
        token: str,
        allowed_chat_ids: set[int] | frozenset[int],
        *,
        session: requests.Session | None = None,
        poll_timeout: int = 20,
    ) -> None:
        token = str(token or "").strip()
        if not token or ":" not in token or any(ch.isspace() for ch in token):
            raise ValueError("invalid Telegram bot token")
        allowed = frozenset(int(value) for value in allowed_chat_ids)
        if not allowed or any(value <= 0 for value in allowed):
            raise ValueError("Telegram private-chat allowlist is required")

        self.bot = bot
        self.allowed_chat_ids = allowed
        self.poll_timeout = max(1, min(int(poll_timeout), 30))
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._session = session or requests.Session()
        self._owns_session = session is None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset = 0

    @classmethod
    def from_env(cls, bot: Any) -> TelegramRemote | None:
        """Build only after an explicit opt-in. Misconfiguration disables remote fail-closed."""
        if not _env_truthy(os.environ.get(_ENV_ENABLED)):
            return None

        token = os.environ.get(_ENV_TOKEN, "").strip()
        try:
            allowed = _parse_allowed_chat_ids(os.environ.get(_ENV_ALLOWED_CHAT_IDS, ""))
        except ValueError:
            log_debug("telegram_remote: disabled because allowed chat ids are invalid")
            return None
        if not token:
            log_debug("telegram_remote: disabled because bot token is missing")
            return None
        if not allowed:
            log_debug("telegram_remote: disabled because private-chat allowlist is empty")
            return None
        try:
            return cls(bot, token, allowed)
        except ValueError:
            # Never include the token (or a requests exception containing its URL) in logs.
            log_debug("telegram_remote: disabled because configuration is invalid")
            return None

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="telegram_remote",
            daemon=True,
        )
        self._thread.start()
        log_debug("telegram_remote: polling started")
        return True

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        if self._owns_session:
            try:
                self._session.close()
            except Exception:
                pass
        self._thread = None
        log_debug("telegram_remote: stopped")

    def _api(self, method: str, payload: dict[str, Any], *, timeout: tuple[float, float]) -> Any:
        response = self._session.post(
            f"{self._base_url}/{method}",
            data=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise RuntimeError("Telegram API returned an unsuccessful response")
        return body.get("result")

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = self._api(
                    "getUpdates",
                    {
                        "offset": self._offset,
                        "timeout": self.poll_timeout,
                        "allowed_updates": json.dumps(["message"]),
                    },
                    timeout=(5.0, float(self.poll_timeout + 8)),
                )
                updates = result if isinstance(result, list) else []
                for update in updates:
                    if self._stop_event.is_set():
                        break
                    if not isinstance(update, dict):
                        continue
                    try:
                        update_id = int(update.get("update_id", -1))
                    except (TypeError, ValueError):
                        update_id = -1
                    # Advance before processing so a malformed command cannot poison the poll loop.
                    if update_id >= 0:
                        self._offset = max(self._offset, update_id + 1)
                    try:
                        self.process_update(update)
                    except Exception as exc:
                        log_debug(f"telegram_remote: update failed ({type(exc).__name__})")
            except Exception as exc:
                # requests exceptions may embed the token-bearing URL. Log only the type.
                log_debug(f"telegram_remote: poll failed ({type(exc).__name__})")
                self._stop_event.wait(2.0)

    def process_update(self, update: dict[str, Any]) -> bool:
        """Process one update. Unauthorized/group chats receive no response at all."""
        message = update.get("message")
        if not isinstance(message, dict):
            return False
        chat = message.get("chat")
        if not isinstance(chat, dict) or str(chat.get("type") or "") != "private":
            return False
        try:
            chat_id = int(chat.get("id"))
        except (TypeError, ValueError):
            return False
        if chat_id not in self.allowed_chat_ids:
            log_debug("telegram_remote: ignored message from unauthorized private chat")
            return False

        text = str(message.get("text") or "").strip()
        if not text.startswith("/"):
            return False
        command = text.split(None, 1)[0].split("@", 1)[0].lower()
        if command in ("/start", "/help"):
            reply = self._help_text()
        elif command == "/status":
            reply = self._status_text()
        elif command == "/accounts":
            reply = self._accounts_text()
        else:
            reply = "Неизвестная команда. /help покажет доступные команды."
        self._send_message(chat_id, reply)
        return True

    def _send_message(self, chat_id: int, text: str) -> None:
        # Telegram caps sendMessage text at 4096 chars. Leave room for future annotations.
        safe_text = str(text or "")[:3900]
        self._api(
            "sendMessage",
            {
                "chat_id": int(chat_id),
                "text": safe_text,
                "disable_web_page_preview": "true",
            },
            timeout=(5.0, 15.0),
        )

    def _iter_states(self) -> list[tuple[int, Any]]:
        regular = list(getattr(self.bot, "account_states", []) or [])
        result: list[tuple[int, Any]] = list(enumerate(regular))
        temp_states = getattr(self.bot, "temp_states", {}) or {}
        if isinstance(temp_states, dict):
            for raw_idx, state in sorted(temp_states.items(), key=lambda item: str(item[0])):
                try:
                    public_idx = len(regular) + int(raw_idx)
                except (TypeError, ValueError):
                    continue
                result.append((public_idx, state))
        return result

    @staticmethod
    def _state_view(idx: int, state: Any) -> dict[str, Any]:
        lock = getattr(state, "_state_lock", None)
        context = lock if lock is not None else nullcontext()
        with context:
            return {
                "idx": idx,
                "short": str(getattr(state, "short", "") or getattr(state, "name", "") or f"#{idx}"),
                "status": str(getattr(state, "status", "") or "idle"),
                "detail": str(getattr(state, "status_detail", "") or ""),
                "paused": bool(getattr(state, "paused", False)),
                "paused_reason": str(getattr(state, "paused_reason", "") or ""),
                "hard_stopped": bool(getattr(state, "hard_stopped", False)),
                "daily_sent": int(getattr(state, "daily_sent", 0) or 0),
                "sent": int(getattr(state, "sent", 0) or 0),
                "found": int(getattr(state, "found_vacancies", 0) or 0),
                "queue": len(list(getattr(state, "vacancies_queue", []) or [])),
                "pending_chats": int(getattr(state, "llm_pending_chats", 0) or 0),
            }

    def _views(self) -> list[dict[str, Any]]:
        return [self._state_view(idx, state) for idx, state in self._iter_states()]

    @staticmethod
    def _help_text() -> str:
        return (
            "HH Bot · Telegram remote\n"
            "Phase 6A работает только на чтение.\n\n"
            "/status - общий статус\n"
            "/accounts - состояния аккаунтов\n"
            "/help - эта справка\n\n"
            "Команды, меняющие состояние, появятся отдельным этапом после safety-тестов."
        )

    def _status_text(self) -> str:
        views = self._views()
        paused = sum(1 for item in views if item["paused"])
        hard_stopped = sum(1 for item in views if item["hard_stopped"])
        pending = sum(int(item["pending_chats"]) for item in views)
        daily = sum(int(item["daily_sent"]) for item in views)
        return (
            "HH Bot · статус\n"
            f"Глобально: {'пауза' if bool(getattr(self.bot, 'paused', False)) else 'работает'}\n"
            f"Аккаунтов: {len(views)} · на паузе: {paused} · hard stop: {hard_stopped}\n"
            f"Откликов сегодня (локально): {daily}\n"
            f"Чатов ждут ответа: {pending}\n"
            f"Safe search: {'включён' if bool(getattr(CONFIG, 'search_only_mode', False)) else 'выключен'}"
        )

    def _accounts_text(self) -> str:
        views = self._views()
        if not views:
            return "Аккаунты пока не загружены."
        daily_limit = _effective_daily_limit()
        lines = ["HH Bot · аккаунты"]
        for item in views:
            if item["hard_stopped"]:
                marker = "⛔"
            elif item["paused"]:
                marker = "⏸"
            else:
                marker = "▶"
            daily = str(item["daily_sent"])
            if daily_limit > 0:
                daily += f"/{daily_limit}"
            reason = f" · {item['paused_reason']}" if item["paused_reason"] else ""
            lines.append(
                f"{marker} #{item['idx']} {item['short']}: {item['status']}{reason}\n"
                f"   сегодня {daily} · запуск {item['sent']} · очередь {item['queue']}"
            )
        return "\n".join(lines)[:3900]
