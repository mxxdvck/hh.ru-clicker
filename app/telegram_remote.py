"""Project Phase 6: secure Telegram remote.

Telegram is a thin remote UI over the existing BotManager. It must never become a
second application engine or bypass Phase 1-5 safety, quota, questionnaire or LLM
policy decisions.
"""

from __future__ import annotations

from contextlib import nullcontext
import json
import os
import secrets
import threading
import time
from typing import Any

import requests

from app.config import CONFIG
from app.logging_utils import log_debug


_ENV_ENABLED = "HH_BOT_TELEGRAM_ENABLED"
_ENV_TOKEN = "HH_BOT_TELEGRAM_TOKEN"
_ENV_ALLOWED_CHAT_IDS = "HH_BOT_TELEGRAM_ALLOWED_CHAT_IDS"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_CONFIRM_TTL_SECONDS = 90.0


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
    """Small Bot API long-polling client with a private-chat allowlist."""

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
        self._pending_lock = threading.Lock()
        self._pending_actions: dict[int, dict[str, Any]] = {}

    @classmethod
    def from_env(cls, bot: Any) -> TelegramRemote | None:
        """Build only after explicit opt-in. Misconfiguration disables remote fail-closed."""
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
        with self._pending_lock:
            self._pending_actions.clear()
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
        parts = text.split()
        command = parts[0].split("@", 1)[0].lower()
        args = parts[1:]

        if command in ("/start", "/help"):
            reply = self._help_text()
        elif command == "/status":
            reply = self._status_text()
        elif command == "/accounts":
            reply = self._accounts_text()
        elif command == "/pause":
            reply = self._prepare_global_pause(chat_id, True)
        elif command == "/resume":
            reply = self._prepare_global_pause(chat_id, False)
        elif command == "/account":
            reply = self._prepare_account_pause(chat_id, args)
        elif command == "/apply_queue":
            reply = self._prepare_apply(chat_id, args, exact_subset=False)
        elif command == "/apply":
            reply = self._prepare_apply(chat_id, args, exact_subset=True)
        elif command == "/confirm":
            reply = self._confirm(chat_id, args)
        elif command == "/cancel":
            reply = self._cancel(chat_id)
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

    def _state_for_index(self, idx: int) -> Any | None:
        if idx < 0:
            return None
        regular = list(getattr(self.bot, "account_states", []) or [])
        if idx < len(regular):
            return regular[idx]
        temp_states = getattr(self.bot, "temp_states", {}) or {}
        if not isinstance(temp_states, dict):
            return None
        return temp_states.get(idx - len(regular))

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
            "HH Bot · Telegram remote\n\n"
            "/status - общий статус\n"
            "/accounts - состояния аккаунтов\n"
            "/pause | /resume - глобальная пауза\n"
            "/account <idx> pause|resume - пауза аккаунта\n"
            "/apply_queue <idx> - текущая safe-search очередь\n"
            "/apply <idx> <vacancy_id...> - точный поднабор safe-search\n"
            "/confirm <код> - подтвердить изменение\n"
            "/cancel - отменить ожидающее изменение\n"
            "/help - эта справка\n\n"
            "Любое изменение состояния требует одноразового подтверждения. Force/bypass команд нет."
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

    def _store_pending(self, chat_id: int, action: dict[str, Any], label: str) -> str:
        token = secrets.token_hex(4)
        pending = dict(action)
        pending["token"] = token
        pending["expires_at"] = time.monotonic() + _CONFIRM_TTL_SECONDS
        pending["label"] = label
        with self._pending_lock:
            # One pending action per authorized chat. A new request replaces the old one.
            self._pending_actions[chat_id] = pending
        return (
            f"Подтвердить: {label}\n"
            f"/confirm {token}\n"
            "Код одноразовый и действует 90 секунд. /cancel отменит действие."
        )

    def _prepare_global_pause(self, chat_id: int, paused: bool) -> str:
        current = bool(getattr(self.bot, "paused", False))
        if current == paused:
            return "Глобальная пауза уже включена." if paused else "Бот уже продолжает работу."
        label = "поставить весь бот на паузу" if paused else "снять глобальную паузу"
        return self._store_pending(chat_id, {"kind": "global_pause", "paused": paused}, label)

    def _prepare_account_pause(self, chat_id: int, args: list[str]) -> str:
        if len(args) != 2:
            return "Формат: /account <idx> pause|resume"
        try:
            idx = int(args[0])
        except ValueError:
            return "idx должен быть целым числом."
        desired_text = args[1].strip().lower()
        if desired_text not in ("pause", "resume"):
            return "Формат: /account <idx> pause|resume"
        state = self._state_for_index(idx)
        if state is None:
            return "Аккаунт с таким idx не найден."
        paused = desired_text == "pause"
        view = self._state_view(idx, state)
        if bool(view["paused"]) == paused:
            return f"Аккаунт #{idx} уже {'на паузе' if paused else 'работает'}."
        label = f"{'поставить' if paused else 'возобновить'} аккаунт #{idx} {view['short']}"
        return self._store_pending(
            chat_id,
            {"kind": "account_pause", "idx": idx, "paused": paused},
            label,
        )

    def _safe_queue_snapshot(self, idx: int) -> tuple[Any | None, tuple[str, ...], str]:
        state = self._state_for_index(idx)
        if state is None:
            return None, (), ""
        lock = getattr(state, "_state_lock", None)
        context = lock if lock is not None else nullcontext()
        with context:
            queue = tuple(str(value).strip() for value in (getattr(state, "vacancies_queue", []) or []))
            queue = tuple(value for value in queue if value)
            reason = str(getattr(state, "paused_reason", "") or "")
            paused = bool(getattr(state, "paused", False))
        if not paused:
            reason = ""
        return state, queue, reason

    def _prepare_apply(self, chat_id: int, args: list[str], *, exact_subset: bool) -> str:
        if not args:
            return (
                "Формат: /apply <idx> <vacancy_id...>"
                if exact_subset
                else "Формат: /apply_queue <idx>"
            )
        try:
            idx = int(args[0])
        except ValueError:
            return "idx должен быть целым числом."
        if not bool(getattr(CONFIG, "search_only_mode", False)):
            return "Safe-search режим сейчас выключен; Telegram не запускает прямой apply."
        state, queue, pause_reason = self._safe_queue_snapshot(idx)
        if state is None:
            return "Аккаунт с таким idx не найден."
        if pause_reason != "search_only" or not queue:
            return "Для аккаунта нет текущей подтверждаемой safe-search очереди."

        selected = queue
        if exact_subset:
            raw_ids: list[str] = []
            for raw in args[1:]:
                raw_ids.extend(part.strip() for part in raw.split(",") if part.strip())
            if not raw_ids:
                return "Формат: /apply <idx> <vacancy_id...>"
            queue_set = set(queue)
            selected_list: list[str] = []
            seen: set[str] = set()
            for vacancy_id in raw_ids:
                if vacancy_id in seen:
                    continue
                if vacancy_id not in queue_set:
                    return f"Вакансия {vacancy_id} не входит в текущую safe-search очередь."
                seen.add(vacancy_id)
                selected_list.append(vacancy_id)
            selected = tuple(selected_list)

        view = self._state_view(idx, state)
        label = f"откликнуться на {len(selected)} вакансий из safe-search для #{idx} {view['short']}"
        # Capture the exact ids now. apply_search_results validates the same ids again at confirm time.
        return self._store_pending(
            chat_id,
            {"kind": "apply", "idx": idx, "vacancy_ids": selected},
            label,
        )

    def _cancel(self, chat_id: int) -> str:
        with self._pending_lock:
            existed = self._pending_actions.pop(chat_id, None) is not None
        return "Ожидающее действие отменено." if existed else "Нет действия для отмены."

    def _confirm(self, chat_id: int, args: list[str]) -> str:
        if len(args) != 1:
            return "Формат: /confirm <код>"
        supplied = str(args[0]).strip()
        with self._pending_lock:
            pending = self._pending_actions.get(chat_id)
            if pending is None:
                return "Нет ожидающего действия."
            if float(pending.get("expires_at", 0.0)) < time.monotonic():
                self._pending_actions.pop(chat_id, None)
                return "Код подтверждения истёк. Повтори исходную команду."
            expected = str(pending.get("token") or "")
            if not supplied or not secrets.compare_digest(supplied, expected):
                return "Неверный код подтверждения."
            # Consume before execution: confirmation is one-shot even if the operation fails.
            pending = self._pending_actions.pop(chat_id)
        return self._execute_pending(pending)

    def _execute_pending(self, action: dict[str, Any]) -> str:
        kind = str(action.get("kind") or "")
        if kind == "global_pause":
            desired = bool(action.get("paused"))
            current = bool(getattr(self.bot, "paused", False))
            if current == desired:
                return "Состояние уже изменилось, повторный toggle не нужен."
            self.bot.toggle_pause()
            if bool(getattr(self.bot, "paused", False)) != desired:
                return "Не удалось подтвердить новое глобальное состояние."
            return "✅ Глобальная пауза включена." if desired else "✅ Глобальная пауза снята."

        if kind == "account_pause":
            try:
                idx = int(action.get("idx"))
            except (TypeError, ValueError):
                return "Действие отклонено: некорректный idx."
            desired = bool(action.get("paused"))
            state = self._state_for_index(idx)
            if state is None:
                return "Действие отклонено: аккаунт больше не существует."
            current = bool(self._state_view(idx, state)["paused"])
            if current == desired:
                return "Состояние аккаунта уже изменилось, повторный toggle не нужен."
            self.bot.toggle_account_pause(idx)
            state = self._state_for_index(idx)
            if state is None or bool(self._state_view(idx, state)["paused"]) != desired:
                return "Не удалось подтвердить новое состояние аккаунта."
            return f"✅ Аккаунт #{idx} {'на паузе' if desired else 'возобновлён'}."

        if kind == "apply":
            try:
                idx = int(action.get("idx"))
            except (TypeError, ValueError):
                return "Действие отклонено: некорректный idx."
            vacancy_ids = [str(value) for value in (action.get("vacancy_ids") or ()) if str(value)]
            if not vacancy_ids:
                return "Действие отклонено: подтверждённый список пуст."
            ok = bool(self.bot.apply_search_results(idx, vacancy_ids=vacancy_ids))
            if not ok:
                return (
                    "Действие отклонено сервером. Safe-search очередь могла измениться, "
                    "аккаунт мог выйти из search_only или список больше не валиден."
                )
            return f"✅ Подтверждено {len(vacancy_ids)} вакансий. Запущен существующий safe apply-flow."

        return "Действие отклонено: неизвестный тип операции."
