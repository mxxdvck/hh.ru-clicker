"""GUI routes for autosearches, hidden objects, notifications and conversion."""

import asyncio

from fastapi import APIRouter, Request

from app.hh_mobile_transport import MobileAPIError
from app.instances import bot
from app.mobile_autosearch import delete_autosearch, fetch_autosearches, update_autosearch
from app.mobile_discovery import fetch_bell_notifications, fetch_hidden, restore_hidden
from app.storage import get_applied_list, get_interviews_list
from app.application_ledger import get_status_counts


router = APIRouter()


def _acc(idx: int):
    return bot._get_apply_acc(idx) if idx >= 0 else None


def _state(idx: int):
    if 0 <= idx < len(bot.account_states):
        return bot.account_states[idx]
    return bot.temp_states.get(idx - len(bot.account_states))


async def _run(func, *args):
    try:
        return await asyncio.get_event_loop().run_in_executor(None, func, *args)
    except MobileAPIError as exc:
        return {"ok": False, "error": f"HH API: {exc.status_code}"}


@router.get("/api/account/{idx}/autosearches")
async def api_autosearches(idx: int):
    acc = _acc(idx)
    return await _run(fetch_autosearches, acc) if acc else {"ok": False, "error": "Аккаунт не найден"}


@router.put("/api/account/{idx}/autosearches/{search_id}")
async def api_autosearch_update(idx: int, search_id: str, request: Request):
    acc = _acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    body = await request.json()
    return await _run(
        lambda: update_autosearch(acc, search_id, name=body.get("name"),
                                  email_subscription=body.get("email_subscription")))


@router.delete("/api/account/{idx}/autosearches/{search_id}")
async def api_autosearch_delete(idx: int, search_id: str):
    acc = _acc(idx)
    return await _run(delete_autosearch, acc, search_id) if acc else {"ok": False, "error": "Аккаунт не найден"}


@router.get("/api/account/{idx}/hidden")
async def api_hidden(idx: int):
    acc = _acc(idx)
    return await _run(fetch_hidden, acc) if acc else {"ok": False, "error": "Аккаунт не найден"}


@router.delete("/api/account/{idx}/hidden/{kind}/{object_id}")
async def api_hidden_restore(idx: int, kind: str, object_id: str):
    acc = _acc(idx)
    return await _run(restore_hidden, acc, kind, object_id) if acc else {"ok": False, "error": "Аккаунт не найден"}


@router.get("/api/account/{idx}/bell_notifications")
async def api_bell_notifications(idx: int):
    acc = _acc(idx)
    return await _run(fetch_bell_notifications, acc) if acc else {"ok": False, "error": "Аккаунт не найден"}


@router.get("/api/account/{idx}/conversion")
async def api_conversion(idx: int):
    acc = _acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    name = str(acc.get("name") or "")
    applied = [x for x in get_applied_list(5000) if x.get("account") == name]
    interviews = get_interviews_list(acc=name, limit=5000)
    invited = {
        str(x.get("vacancy_id") or x.get("vid") or "") for x in interviews
        if x.get("vacancy_id") or x.get("vid")
    }
    applied_ids = {str(x.get("vacancy_id") or "") for x in applied}
    # Old interview records did not persist vacancy_id. The account worker's
    # HH counter is authoritative in that case; use exact local matching only
    # when it is available.
    matched_local = len(applied_ids & invited)
    state = _state(idx)
    matched = max(matched_local, int(getattr(state, "hh_interviews", 0) or 0))
    matched = min(matched, len(applied_ids))
    return {
        "ok": True, "applied": len(applied_ids), "interviews": matched,
        "conversion_percent": round(matched * 100 / len(applied_ids), 1) if applied_ids else 0,
    }


@router.get("/api/account/{idx}/operations_summary")
async def api_operations_summary(idx: int):
    """Phase 5F read-model: live cycle, durable outcomes and ledger reliability."""
    acc = _acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}

    conversion = await api_conversion(idx)
    state = _state(idx)
    status_counts = get_status_counts(str(acc.get("name") or ""))
    filter_stats = dict(getattr(state, "filter_stats", {}) or {}) if state else {}

    found = None
    filtered = None
    queue = None
    sent_today = None
    if state:
        if filter_stats:
            found = int(filter_stats.get("raw_collected", getattr(state, "found_vacancies", 0)) or 0)
            filtered = int(filter_stats["accepted"]) if "accepted" in filter_stats else None
            queue = len(list(getattr(state, "vacancies_queue", []) or []))
        sent_today = int(getattr(state, "daily_sent", 0) or 0)

    hh_stats_known = bool(getattr(state, "hh_stats_updated", None)) if state else False
    viewed = int(getattr(state, "hh_viewed", 0) or 0) if hh_stats_known else None
    normalized = {
        key: int(status_counts.get(key, 0) or 0)
        for key in (
            "applying", "applied", "already", "interrupted",
            "failed_transient", "failed_permanent",
        )
    }
    return {
        "ok": True,
        "account": str(acc.get("name") or ""),
        "cycle": {
            "found": found, "filtered": filtered, "queue": queue,
            "sent_today": sent_today,
            "status": str(getattr(state, "status", "") or "") if state else "",
        },
        "outcome": {
            "applied": int(conversion.get("applied", 0) or 0),
            "viewed": viewed,
            "interviews": int(conversion.get("interviews", 0) or 0),
            "conversion_percent": conversion.get("conversion_percent", 0),
        },
        "ledger": {"total": sum(normalized.values()), "statuses": normalized},
        "sources": {
            "cycle": "current worker snapshot",
            "applied": "local applied history",
            "viewed": "HH negotiation statistics" if hh_stats_known else "unavailable",
            "interviews": "local interview identity + HH account counter",
            "ledger": "applications.sqlite3",
        },
    }
