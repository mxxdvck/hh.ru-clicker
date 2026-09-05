"""
Settings and raw config/accounts routes.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Union

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import CONFIG, accounts_data, _CONFIG_KEYS, save_config, save_accounts
from app.storage import load_browser_sessions, save_browser_sessions, DATA_DIR
from app.logging_utils import log_debug
from app.secure_store import (
    SecureStoreError, backend_name, decode_envelope, encode_envelope,
    is_secure_envelope, read_json as secure_read_json,
    write_json_atomic as secure_write_json,
)


router = APIRouter()


def _quiesce_runtime(bot) -> None:
    """Остановить account/temp workers без глобального stop_event manager-а."""
    states = list(bot.account_states) + list(bot.temp_states.values())
    for state in states:
        state._deleted = True
        state.paused = True
        ws = getattr(state, "_ws_client", None)
        if ws:
            try:
                ws.stop()
            except Exception:
                pass
    for state in states:
        for worker in getattr(state, "_workers", []):
            try:
                worker.join(timeout=5)
            except Exception:
                pass
    bot.account_states.clear()
    bot.temp_states.clear()


class ConfigUpdate(BaseModel):
    key: str
    # Pydantic union resolves left-to-right; bool(300000)=True раньше int → коэрсия
    # рушит integer config keys. Порядок: int → float → bool → str (kimi-r14-4 #5).
    value: Union[int, float, bool, str]


def _safe_cast(key: str, value):
    """Cast `value` to the type of `CONFIG.<key>`. Raises ValueError on mismatch.
    Prevents type confusion (e.g. dict where int expected) и сохраняет инварианты Config.
    """
    old_val = getattr(CONFIG, key)
    expected = type(old_val)
    if expected is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0", "yes", "no"):
            return value.lower() in ("true", "1", "yes")
        raise ValueError(f"{key} expects bool, got {type(value).__name__}")
    if expected in (int, float):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return expected(value)
        if isinstance(value, str):
            return expected(value)
        raise ValueError(f"{key} expects {expected.__name__}, got {type(value).__name__}")
    if expected is str:
        return str(value)
    if expected in (list, dict):
        if not isinstance(value, expected):
            raise ValueError(f"{key} expects {expected.__name__}, got {type(value).__name__}")
        return value
    if isinstance(value, expected):
        return value
    raise ValueError(f"{key}: cannot cast {type(value).__name__} to {expected.__name__}")


@router.post("/api/settings")
async def api_settings(update: ConfigUpdate):
    if update.key not in _CONFIG_KEYS:
        return {"ok": False, "error": "Unknown key"}
    try:
        setattr(CONFIG, update.key, _safe_cast(update.key, update.value))
    except (ValueError, TypeError) as e:
        return {"ok": False, "error": str(e)}
    save_config()
    return {"ok": True, "key": update.key, "value": getattr(CONFIG, update.key)}


_RAW_LIST_KEYS = {
    "questionnaire_templates", "letter_templates", "url_pool",
    "allowed_schedules", "title_include_keywords", "title_exclude_keywords",
    "llm_profiles",
}
_RAW_LLM_KEYS = {
    "llm_enabled", "llm_auto_send", "llm_use_cover_letter", "llm_generate_cover_letter", "llm_use_resume",
    "llm_api_key", "llm_base_url", "llm_model", "llm_applicant_gender", "llm_profile_mode",
    "llm_system_prompt", "llm_openclaw_enabled", "llm_openclaw_agent",
    "llm_openclaw_model", "llm_openclaw_timeout",
}
_RAW_EXTRA_KEYS = {"auto_apply_tests"}


def _all_raw_config_keys():
    """Все ключи которые покажем/примем в raw editor: whitelist + LLM + lists."""
    return set(_CONFIG_KEYS) | _RAW_LIST_KEYS | _RAW_LLM_KEYS | _RAW_EXTRA_KEYS


_SECRET_MASK = "***"

def _masked_llm_profiles(profiles):
    safe = []
    for profile in profiles or []:
        if not isinstance(profile, dict):
            continue
        item = dict(profile)
        key = str(item.get("api_key") or "")
        item["api_key"] = _SECRET_MASK if key else ""
        item["key_set"] = bool(key)
        safe.append(item)
    return safe

def _merge_llm_profile_secrets(incoming, current):
    current = [p for p in (current or []) if isinstance(p, dict)]
    def ident(p):
        return (str(p.get("name") or "").strip(), str(p.get("base_url") or "").strip(),
                str(p.get("model") or "").strip())
    by_ident = {ident(p): p for p in current}
    by_name = {str(p.get("name") or "").strip(): p for p in current if p.get("api_key")}
    merged = []
    for pos, raw in enumerate(incoming):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item.pop("key_set", None)
        key = str(item.get("api_key") or "")
        if key in ("", _SECRET_MASK):
            old = by_ident.get(ident(item)) or by_name.get(str(item.get("name") or "").strip())
            if not old and pos < len(current):
                old = current[pos]
            item["api_key"] = str((old or {}).get("api_key") or "")
        merged.append(item)
    return merged



@router.get("/api/raw/config")
async def api_raw_config_get():
    """Return raw-editor config without exposing credential values."""
    out = {}
    for key in sorted(_all_raw_config_keys()):
        if not hasattr(CONFIG, key):
            continue
        value = getattr(CONFIG, key)
        if key == "llm_api_key":
            out[key] = _SECRET_MASK if str(value or "").strip() else ""
        elif key == "llm_profiles":
            out[key] = _masked_llm_profiles(value)
        elif key == "hh_proxy_url" and isinstance(value, str) and "@" in value:
            out[key] = _SECRET_MASK
        else:
            out[key] = value
    return out


@router.post("/api/raw/config")
async def api_raw_config_set(request: Request, force: int = 0):
    """Перезаписать config из JSON-объекта. Принимает все известные ключи
    (включая llm_*). Строгий кастинг типов.
    Защита: если пустой list/string затирает непустой существующий → пропуск
    (если не передан ?force=1). Иначе один случайный «💾 Сохранить» при stale-state
    сносит llm_profiles/letter_templates/cookies."""
    try:
        data = await request.json()
    except Exception:
        return {"ok": False, "error": "Невалидный JSON"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "Ожидается объект"}
    errors = {}
    preserved = []  # ключи которые НЕ перезаписали из-за защиты
    allowed = _all_raw_config_keys()
    for key, value in data.items():
        if key not in allowed:
            errors[key] = "unknown_or_wrong_type"
            continue
        if key in _RAW_LIST_KEYS:
            if not isinstance(value, list):
                errors[key] = "expected list"
                continue
            current = getattr(CONFIG, key, None) or []
            if not force and not value and current:
                preserved.append(key)
                continue
            if key == "llm_profiles":
                value = _merge_llm_profile_secrets(value, current)
            setattr(CONFIG, key, value)
            continue
        if key in _RAW_LLM_KEYS or key in _RAW_EXTRA_KEYS or key in _CONFIG_KEYS:
            try:
                casted = _safe_cast(key, value)
            except (ValueError, TypeError) as e:
                errors[key] = str(e)
                continue
            current = getattr(CONFIG, key, None)
            if key in {"llm_api_key", "hh_proxy_url"} and casted == _SECRET_MASK and current:
                preserved.append(key)
                continue
            # Защита от затирания непустых строк (например llm_api_key, llm_system_prompt)
            if not force and isinstance(casted, str) and not casted and isinstance(current, str) and current:
                preserved.append(key)
                continue
            setattr(CONFIG, key, casted)
    save_config()
    return {"ok": not errors, "errors": errors, "preserved": preserved}


@router.get("/api/raw/accounts")
async def api_raw_accounts_get():
    """Вернуть accounts без значений cookies (только ключи)."""
    safe = []
    for acc in accounts_data:
        a = {k: v for k, v in acc.items() if k != "cookies"}
        a["cookies"] = {k: "***" for k in acc.get("cookies", {})}
        safe.append(a)
    return safe


@router.post("/api/raw/accounts")
async def api_raw_accounts_set(request: Request):
    """Перезаписать accounts. Значение cookies '***' сохраняет старое."""
    try:
        data = await request.json()
    except Exception:
        return {"ok": False, "error": "Невалидный JSON"}
    if not isinstance(data, list):
        return {"ok": False, "error": "Ожидается массив"}
    old_by_name = {a.get("name", ""): a for a in accounts_data}
    merged = []
    for acc in data:
        if not isinstance(acc, dict):
            continue
        name = acc.get("name", "")
        old = old_by_name.get(name, {})
        new_cookies = acc.get("cookies", {})
        merged_cookies = {
            k: (old.get("cookies", {}).get(k, "") if v == "***" else v)
            for k, v in new_cookies.items()
        }
        for k, v in old.get("cookies", {}).items():
            if k not in merged_cookies:
                merged_cookies[k] = v
        acc = dict(acc)
        acc["cookies"] = merged_cookies
        merged.append(acc)
    # Atomic swap: clear()+extend() — non-atomic, readers могут увидеть [] между ними.
    accounts_data[:] = merged
    save_accounts()
    # Обновляем in-memory acc dict для уже-работающих AccountState'ов:
    # если имя совпадает — переписываем cookies/letter/urls/use_oauth.
    # Воркеры тут же подхватят свежие куки на следующем HTTP-запросе. Полная
    # пересборка account_states тут небезопасна — убъёт running threads.
    try:
        from app.instances import bot as _bot
        from app.logging_utils import log_debug
        by_name = {a.get("name", ""): a for a in merged}
        retained_states = {}
        for state in _bot.account_states:
            new_acc = by_name.get(state.name)
            if not new_acc:
                state._deleted = True
                state.paused = True
                ws = getattr(state, "_ws_client", None)
                if ws:
                    try:
                        ws.stop()
                    except Exception:
                        pass
                continue
            # In-place mutation (НЕ replace reference): workers держат ссылку на
            # state.acc и stale dict иначе (r13-1 #5). Cookies_lock сохраняем явно.
            # Pop+update должны быть атомарными — иначе reader увидит частично-
            # очищенный dict (например, отсутствие cookies в момент HTTP-запроса).
            # Держим state._state_lock на всю последовательность (kimi-r14-1 #5).
            with state._state_lock:
                cookies_lock = state.acc.get("_cookies_lock")
                keep_keys = set(new_acc.keys()) | {"_cookies_lock"}
                for k in list(state.acc.keys()):
                    if k not in keep_keys:
                        state.acc.pop(k, None)
                state.acc.update(new_acc)
                if cookies_lock is not None:
                    state.acc["_cookies_lock"] = cookies_lock
                state.cookies_expired = False
            retained_states[state.name] = state
        _bot.account_states[:] = [retained_states[a.get("name", "")] for a in merged
                                 if a.get("name", "") in retained_states]
    except Exception as e:
        log_debug(f"api_raw_accounts_set live-sync error: {e}")
    return {
        "ok": True,
        "count": len(merged),
        "warning": "Удаления применены сразу. Добавление новых аккаунтов требует перезапуска бота.",
    }


# ============================================================
# BACKUP / RESTORE — единый JSON со всем (включая cookies/API-keys).
# Доступ ВСЕГДА требует API-key — проверка в middleware (app/routes/__init__.py,
# _ALWAYS_AUTH_PREFIXES), даже при пустом HH_BOT_API_KEY.
# ============================================================

_BACKUP_FILES = ("config.json", "accounts.json", "browser_sessions.json", "oauth_tokens.json")


def _load_json_file(name: str):
    p = Path(DATA_DIR) / name
    if not p.exists():
        return None
    try:
        return secure_read_json(p, None, migrate=True)
    except Exception as e:
        log_debug(f"backup: failed to load {name}: {e}")
        return None


_REDACT_KEYS = {
    "api_key", "llm_api_key", "access_token", "refresh_token", "client_secret",
    "oauth_client_secret", "app_client_token", "password", "cookie", "cookies",
    "authorization", "hhtoken", "hhtokenxs", "_xsrf",
}

def _redact_backup_value(value, key: str = ""):
    key_l = str(key).lower()
    if key_l in _REDACT_KEYS or key_l.endswith("_token") or key_l.endswith("_secret"):
        if isinstance(value, dict):
            return {k: "***" for k in value}
        return "***" if value not in (None, "") else value
    if isinstance(value, dict):
        return {k: _redact_backup_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_backup_value(v, key) for v in value]
    if isinstance(value, str) and "@" in value and "://" in value:
        # Proxy URLs may carry user:password@host. Do not export credentials.
        import re as _re
        return _re.sub(r"(://)[^/@:]+:[^/@]+@", r"\1***:***@", value)
    return value


def _redacted_backup(bundle: dict) -> dict:
    out = _redact_backup_value(bundle)
    out["redacted"] = True
    return out


@router.get("/api/backup")
async def api_backup_download(redacted: int = 0):
    """Download a backup without exposing secrets as plaintext."""
    bundle = {
        "version": 2,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }
    for fname in _BACKUP_FILES:
        bundle[fname] = _load_json_file(fname)

    provider = backend_name()
    force_redacted = bool(redacted) or provider == "plaintext"
    headers = {"Cache-Control": "no-store"}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if force_redacted:
        export = _redacted_backup(bundle)
        filename = f"hh-backup-redacted-{stamp}.json"
        headers["X-HH-Backup-Redacted"] = "1"
        if provider == "plaintext" and not redacted:
            headers["X-HH-Backup-Warning"] = "encryption-backend-unavailable"
    else:
        export = encode_envelope(bundle, provider)
        export["backup_format"] = "hh-clicker-encrypted-backup-v2"
        filename = f"hh-backup-encrypted-{stamp}.json"
        headers["X-HH-Backup-Encrypted"] = provider
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    body = json.dumps(export, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(content=body, media_type="application/json", headers=headers)


# Поля внутри каждого файла бэкапа, которые НЕЛЬЗЯ затирать пустым list/string
# без явного ?force=1 — если в бэкапе они пустые, а на диске не пустые → пропуск.
# Это защита от случайного «💾 Сохранить» когда редактор показывал stale-state
# (юзер открыл, не дождался автозагрузки, нажал save → потерял llm_profiles).
_PROTECTED_FIELDS = {
    "config.json": {
        "llm_profiles", "letter_templates", "questionnaire_templates",
        "url_pool", "allowed_schedules",
        "llm_api_key", "llm_base_url", "llm_model", "llm_system_prompt",
    },
}


def _merge_preserve(payload, current, protected: set, path: str = "") -> tuple:
    """Если payload[k] — пустой list/string, а current[k] — непустой — оставляем current.
    Возвращает (merged, preserved_keys)."""
    preserved = []
    if not isinstance(payload, dict) or not isinstance(current, dict):
        return payload, preserved
    out = dict(payload)
    for k in protected:
        new_v = payload.get(k)
        old_v = current.get(k)
        if old_v and not new_v and (isinstance(new_v, (list, str)) or new_v is None):
            out[k] = old_v
            preserved.append(f"{path}{k}")
    return out, preserved


@router.post("/api/backup")
async def api_backup_restore(request: Request, force: int = 0):
    """Восстановить из бэкапа. Принимает JSON, сделанный GET /api/backup.
    Перезаписывает ВСЕ data/*.json файлы. Защита: пустые list/string не затирают
    непустые существующие (для llm_profiles, letter_templates и т.д.) если ?force=0."""
    try:
        data = await request.json()
    except Exception:
        return {"ok": False, "error": "Невалидный JSON"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "Backup payload must be a JSON object"}
    if is_secure_envelope(data):
        try:
            data = decode_envelope(data)
        except SecureStoreError as exc:
            return {"ok": False, "error": f"Cannot decrypt backup: {exc}"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "Decrypted backup has an invalid format"}
    if data.get("redacted") is True:
        return {"ok": False, "error": "Redacted backup cannot restore secrets"}
    if not any(name in data for name in _BACKUP_FILES):
        return {"ok": False, "error": "Backup contains no supported data files"}
    restored = []
    errors = {}
    preserved_all = []
    from app.instances import bot as _bot
    _quiesce_runtime(_bot)
    for fname in _BACKUP_FILES:
        if fname not in data:
            continue
        payload = data[fname]
        if payload is None:
            continue
        # Защита: для известных файлов сохраняем непустые поля если входящие пустые.
        if not force and fname in _PROTECTED_FIELDS:
            current = _load_json_file(fname) or {}
            payload, preserved_keys = _merge_preserve(
                payload, current, _PROTECTED_FIELDS[fname], path=f"{fname}/"
            )
            preserved_all.extend(preserved_keys)
        try:
            # Аудит 2026-08-17 #9: раньше restore писал через фиксированный
            # `<name>.tmp` — тот же путь, что и обычные save_* writers → гонка
            # unlink/replace могла удалить чужой tmp или откатить только что
            # сохранённые изменения. Используем _atomic_write_json (fsync +
            # tmp.replace) для durability и не пересекаемся с writers по имени.
            p = Path(DATA_DIR) / fname
            secure_write_json(p, payload, encrypt=True)
            restored.append(fname)
        except Exception as e:
            errors[fname] = str(e)

    # Reload live state from disk so user не должен рестартовать руками.
    try:
        from app.config import load_config as _load_config, load_accounts as _load_accounts
        _load_config()
        _load_accounts()
        _bot.temp_sessions[:] = load_browser_sessions()
        from app import oauth as _oauth
        _oauth._load_oauth_tokens()
    except Exception as e:
        log_debug(f"backup restore: live-reload error: {e}")

    return {
        "ok": not errors,
        "restored": restored,
        "preserved": preserved_all,
        "errors": errors,
        "warning": "Аккаунты/cookies применены. Для новых аккаунтов нужен перезапуск бота.",
    }


@router.delete("/api/backup")
async def api_backup_wipe():
    """Полная очистка: удалить все data/*.json (config, accounts, browser_sessions,
    oauth_tokens). После — in-memory state сбрасывается до дефолтов."""
    from app.instances import bot as _bot
    _quiesce_runtime(_bot)
    cleared = []
    errors = {}
    for fname in _BACKUP_FILES:
        p = Path(DATA_DIR) / fname
        try:
            if p.exists():
                p.unlink()
                cleared.append(fname)
        except Exception as e:
            errors[fname] = str(e)
    # Сброс in-memory state.
    try:
        from app.config import CONFIG as _CONFIG, Config as _ConfigCls, save_config as _save_config
        accounts_data.clear()
        _bot.temp_sessions.clear()
        save_browser_sessions([], wait=True)
        # Аудит 2026-08-17 #32: раньше файл удаляли, но CONFIG в памяти жил
        # → первый же save_config() возвращал llm_api_key/llm_profiles на диск.
        # Заменяем sensitive-поля CONFIG на дефолтные (из свежего Config()) и
        # атомарно сохраняем очищенное состояние, чтобы утечка была невозможна.
        _defaults = _ConfigCls()
        _SENSITIVE = (
            "llm_api_key", "llm_base_url", "llm_model", "llm_profiles",
            "llm_system_prompt", "hh_proxy_url",
        )
        for _f in _SENSITIVE:
            if hasattr(_defaults, _f):
                setattr(_CONFIG, _f, getattr(_defaults, _f))
        _CONFIG.llm_enabled = False
        _CONFIG.llm_auto_send = False
        _save_config()  # запишем чистый файл
    except Exception as e:
        log_debug(f"backup wipe: in-memory clear error: {e}")
    return {
        "ok": not errors,
        "cleared": cleared,
        "errors": errors,
        "warning": "In-memory очищено. Перезапуск бота не требуется.",
    }
