"""Central safety gate for every outbound application path."""

from __future__ import annotations

from dataclasses import dataclass
import threading

from app.config import CONFIG
from app.apply_mode import search_only_blocked
from app import storage
from app.application_ledger import (
    count_applied_today,
    count_current_run,
    count_inflight_today,
    reserve_application,
    PROCESS_RUN_ID,
)


_RESERVE_LOCK = threading.Lock()


@dataclass(frozen=True)
class ApplyDecision:
    allowed: bool
    code: str
    message: str
    daily_used: int = 0
    run_used: int = 0


def _legacy_today_count(account_name: str, date_prefix: str) -> int:
    storage._load_cache()
    count = 0
    with storage._cache_lock:
        rows = (storage._cache_applied or {}).get(account_name, {})
        for info in rows.values() if isinstance(rows, dict) else []:
            if isinstance(info, dict) and str(info.get("at", "")).startswith(date_prefix):
                count += 1
    return count

def _date_prefix(state=None) -> str:
    # Quotas are always based on current Moscow date; stale AccountState.daily_date
    # must never reopen yesterday's quota after midnight or after a paused session.
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d")
    except Exception:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")


def _run_id(state=None) -> str:
    return str(getattr(state, "apply_run_id", "") or PROCESS_RUN_ID)


def quota_usage(account_name: str, state=None) -> tuple[int, int]:
    """Return conservative (daily_used_with_inflight, run_used_with_inflight)."""
    date_prefix = _date_prefix(state)
    legacy = _legacy_today_count(account_name, date_prefix)
    ledger = count_applied_today(account_name, date_prefix)
    inflight = count_inflight_today(account_name, date_prefix)
    state_daily = int(getattr(state, "daily_sent", 0) or 0) if state else 0
    hh_daily = int(getattr(state, "hh_today_applies", 0) or 0) if state else 0
    daily_used = max(legacy, ledger, state_daily, hh_daily) + inflight
    run_used = count_current_run(account_name, _run_id(state))
    return daily_used, run_used


def check_apply_allowed(account_name: str, vacancy_id: str = "", state=None) -> ApplyDecision:
    """Fail closed on search-only, duplicate and quota exhaustion."""
    account_name = str(account_name or "").strip()
    vacancy_id = str(vacancy_id or "").strip()
    if search_only_blocked():
        return ApplyDecision(False, "search_only", "Режим только поиска: отправка откликов запрещена")
    if vacancy_id and storage.is_applied(account_name, vacancy_id):
        return ApplyDecision(False, "already", "Отклик на эту вакансию уже записан как отправленный")

    daily_used, run_used = quota_usage(account_name, state)
    daily_limit = max(int(getattr(CONFIG, "daily_apply_limit", 0) or 0), 0)
    run_limit = max(int(getattr(CONFIG, "run_apply_limit", 0) or 0), 0)
    hh_limit = max(int(getattr(CONFIG, "hh_daily_limit", 0) or 0), 0)

    if daily_limit and daily_used >= daily_limit:
        return ApplyDecision(False, "daily_limit", f"Дневной лимит исчерпан: {daily_used}/{daily_limit}", daily_used, run_used)
    if hh_limit and daily_used >= hh_limit:
        return ApplyDecision(False, "hh_limit", f"HH-лимит исчерпан: {daily_used}/{hh_limit}", daily_used, run_used)
    if run_limit and run_used >= run_limit:
        return ApplyDecision(False, "run_limit", f"Лимит текущего запуска исчерпан: {run_used}/{run_limit}", daily_used, run_used)
    return ApplyDecision(True, "ok", "Разрешено", daily_used, run_used)


def reserve_apply(account_name: str, vacancy_id: str, resume_id: str = "",
                  state=None, source: str = "") -> ApplyDecision:
    """Atomically enforce all quotas and reserve the exact application key."""
    account_name = str(account_name or "").strip()
    vacancy_id = str(vacancy_id or "").strip()
    with _RESERVE_LOCK:
        if search_only_blocked():
            return ApplyDecision(False, "search_only",
                                 "Search-only mode: application sending is disabled")
        if vacancy_id and storage.is_applied(account_name, vacancy_id):
            return ApplyDecision(False, "already",
                                 "Application already recorded as sent")

        date_prefix = _date_prefix(state)
        legacy = _legacy_today_count(account_name, date_prefix)
        state_daily = int(getattr(state, "daily_sent", 0) or 0) if state else 0
        hh_daily = int(getattr(state, "hh_today_applies", 0) or 0) if state else 0
        external_daily = max(legacy, state_daily, hh_daily)
        daily_limit = max(int(getattr(CONFIG, "daily_apply_limit", 0) or 0), 0)
        hh_limit = max(int(getattr(CONFIG, "hh_daily_limit", 0) or 0), 0)
        run_limit = max(int(getattr(CONFIG, "run_apply_limit", 0) or 0), 0)

        ok, reason, daily_used, run_used = reserve_application(
            account_name, vacancy_id, resume_id, source, _run_id(state),
            date_prefix=date_prefix,
            external_daily_used=external_daily,
            daily_limit=daily_limit,
            hh_limit=hh_limit,
            run_limit=run_limit,
        )
        if ok:
            return ApplyDecision(True, "reserved", "Application reserved", daily_used, run_used)

        if reason in {"applied", "already"}:
            return ApplyDecision(False, "already", "Application already sent", daily_used, run_used)
        if reason == "daily_limit":
            return ApplyDecision(False, reason,
                                 f"Daily application limit reached: {daily_used}/{daily_limit}",
                                 daily_used, run_used)
        if reason == "hh_limit":
            return ApplyDecision(False, reason,
                                 f"HH daily limit reached: {daily_used}/{hh_limit}",
                                 daily_used, run_used)
        if reason == "run_limit":
            return ApplyDecision(False, reason,
                                 f"Per-run application limit reached: {run_used}/{run_limit}",
                                 daily_used, run_used)
        return ApplyDecision(False, "in_flight",
                             f"Application blocked by safety ledger: {reason}",
                             daily_used, run_used)

def finalize_apply(account_name: str, vacancy_id: str, resume_id: str,
                   result: str, info: dict | None = None, state=None,
                   questionnaire: bool = False) -> str:
    """Finalize ledger + canonical counters/storage after one reserved attempt."""
    from app.application_ledger import mark_application

    info = info or {}
    status_map = {
        "sent": "applied",
        "already": "already",
        "test": "needs_questionnaire",
        "limit": "released",
        "auth_error": "released",
    }
    status = status_map.get(result)
    if status is None:
        error_type = str(info.get("error_type") or "").lower()
        if error_type in {
            "search_only", "letter_required", "questionnaire_validation",
            "manual_recoverable",
        }:
            status = "released"
        else:
            status = "failed_transient" if info.get("transient") else "failed_permanent"
    detail = str(info.get("raw") or info.get("error_type") or info.get("exception") or "")
    mark_application(account_name, vacancy_id, resume_id, status=status, detail=detail)

    if result == "sent":
        storage.add_applied(account_name, vacancy_id, info)
        if state is not None:
            state.sent = int(getattr(state, "sent", 0) or 0) + 1
            state.daily_sent = int(getattr(state, "daily_sent", 0) or 0) + 1
            if questionnaire:
                state.questionnaire_sent = int(getattr(state, "questionnaire_sent", 0) or 0) + 1
    return status
