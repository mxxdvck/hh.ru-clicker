"""
Data query routes: applied, tests, interviews, vacancies, HR contacts.
"""

import asyncio
import json
import threading

from fastapi import APIRouter, HTTPException

from app.storage import (
    _load_cache, _cache_applied, _cache_tests, _cache_lock,
    get_applied_list, get_vacancy_db, get_test_list,
    get_interviews_list, get_interviews_summary, upsert_interview,
    _save_applied_async, _save_tests_async,
)
from app.config import CONFIG
from app.hh_client_factory import get_client
from app.instances import bot
from app.llm import generate_llm_reply_decision, rewrite_llm_draft
from app.llm_policy import is_reminder_message, latest_unanswered_employer_question
from app.oauth import fetch_negotiation_messages_oauth


router = APIRouter()


@router.get("/api/applied")
async def api_applied(limit: int = 300):
    return get_applied_list(limit)


@router.get("/api/tests")
async def api_tests(limit: int = 300):
    return get_test_list(limit)


def _interview_row(neg_id: str):
    return next((row for row in get_interviews_list(limit=5000) if str(row.get("neg_id") or "") == str(neg_id)), None)


def _state_for_interview(row: dict):
    account = str(row.get("acc") or "").strip()
    states = list(getattr(bot, "account_states", []) or [])
    states += list((getattr(bot, "temp_states", {}) or {}).values())
    for state in states:
        names = {
            str(getattr(state, "short", "") or "").strip(),
            str(getattr(state, "name", "") or "").strip(),
            str((getattr(state, "acc", {}) or {}).get("name") or "").strip(),
        }
        if account in names:
            return state
    return None


def _review_reason(decision) -> str:
    missing = [str(v).strip() for v in (getattr(decision, "missing_facts", None) or []) if str(v).strip()]
    if missing:
        return "Нужно уточнить: " + ", ".join(missing[:4])
    known = {
        "all configured providers failed": "LLM-провайдер временно не смог сформировать ответ",
        "generated text does not look like a direct answer": "ответ получился не по существу вопроса",
        "interest reply contains extra conditions or commitments": "\u043e\u0442\u0432\u0435\u0442 \u043d\u0430 \u043f\u0440\u0438\u0433\u043b\u0430\u0448\u0435\u043d\u0438\u0435 \u0441\u043e\u0434\u0435\u0440\u0436\u0438\u0442 \u0434\u043e\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0435 \u0443\u0441\u043b\u043e\u0432\u0438\u044f \u0438\u043b\u0438 \u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u0441\u0442\u0432\u0430",
        "factual first-person claim lacks trusted evidence": "для ответа не хватает подтверждённых фактов",
        "experience claim is not sufficiently grounded in trusted facts": "описание опыта недостаточно подтверждено резюме",
    }
    raw = str(getattr(decision, "reason", "") or "").strip()
    return known.get(raw, raw) or "Перегенерировано вручную, перед отправкой проверьте ответ"


def _style_regenerate_existing(row: dict, state) -> dict | None:
    existing = str(row.get("llm_reply") or "").strip()
    low = existing.casefold()
    blocked_prefixes = (
        "\u043d\u0443\u0436\u043d\u043e \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c",
        "\u043d\u0443\u0436\u043d\u043e \u0432\u044b\u0431\u0440\u0430\u0442\u044c",
        "robot question",
    )
    if len(existing) < 15 or any(low.startswith(prefix) for prefix in blocked_prefixes):
        return None
    account_key = f"{getattr(state, 'short', row.get('acc', ''))}:{row.get('neg_id', '')}:rewrite"
    rewritten = rewrite_llm_draft(existing, account_key=account_key)
    if not rewritten:
        return None
    reason = (
        "\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u0447\u0430\u0442\u0430 \u0441\u0435\u0439\u0447\u0430\u0441 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430. "
        "\u041f\u0435\u0440\u0435\u0433\u0435\u043d\u0435\u0440\u0438\u0440\u043e\u0432\u0430\u043d \u0442\u043e\u043b\u044c\u043a\u043e \u0441\u0442\u0438\u043b\u044c \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u044e\u0449\u0435\u0433\u043e \u0447\u0435\u0440\u043d\u043e\u0432\u0438\u043a\u0430, "
        "\u0444\u0430\u043a\u0442\u044b \u043d\u0443\u0436\u043d\u043e \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0432\u0440\u0443\u0447\u043d\u0443\u044e."
    )
    neg_id = str(row.get("neg_id") or "")
    upsert_interview(
        neg_id,
        acc=str(row.get("acc") or ""), acc_color=str(row.get("acc_color") or ""),
        employer=str(row.get("employer") or ""), vacancy_title=str(row.get("vacancy_title") or ""),
        vacancy_id=str(row.get("vacancy_id") or ""), employer_last_msg=str(row.get("employer_last_msg") or ""),
        needs_reply=True, llm_reply=rewritten, llm_sent=False, llm_source="llm_regenerated_style_review",
        llm_category=str(row.get("llm_category") or "general"), llm_review_reason=reason,
    )
    return _interview_row(neg_id) or {"neg_id": neg_id, "llm_reply": rewritten}


def _regenerate_interview_sync(neg_id: str) -> dict:
    row = _interview_row(neg_id)
    if not row:
        raise LookupError("Диалог не найден")
    if row.get("llm_sent") or row.get("status") == "replied":
        raise ValueError("Ответ уже отправлен, перегенерация отключена")
    state = _state_for_interview(row)
    if state is None:
        raise LookupError("Аккаунт диалога не найден среди активных аккаунтов")

    acc = state.acc
    history = []
    try:
        if getattr(state, "cookies_expired", False) or CONFIG.chat_use_oauth:
            history = fetch_negotiation_messages_oauth(acc, neg_id, max_messages=60) or []
    except Exception:
        history = []
    if not history:
        try:
            history = get_client(acc).fetch_chat_history(neg_id, max_messages=60) or []
        except Exception:
            history = []
    employer_last = str(row.get("employer_last_msg") or "")
    if is_reminder_message(employer_last) and not latest_unanswered_employer_question(history):
        try:
            extended = fetch_negotiation_messages_oauth(acc, neg_id, max_messages=60) or []
            if extended:
                history = extended
        except Exception:
            pass
    if is_reminder_message(employer_last) and not latest_unanswered_employer_question(history):
        styled = _style_regenerate_existing(row, state)
        if styled:
            return styled
    if not history and row.get("employer_last_msg"):
        history = [{"sender": "employer", "text": str(row.get("employer_last_msg") or "")}]
    if not history:
        raise ValueError("Не удалось загрузить историю чата")

    resume_text = ""
    if CONFIG.llm_use_resume:
        try:
            resume_data = get_client(acc).fetch_resume()
            resume_text = (resume_data.get("text", "") if isinstance(resume_data, dict) and "text" in resume_data
                           else json.dumps(resume_data, ensure_ascii=False))
        except Exception:
            resume_text = ""
    cover_letter = acc.get("letter", "") if CONFIG.llm_use_cover_letter else ""
    decision = generate_llm_reply_decision(
        history,
        str(row.get("employer") or ""),
        cover_letter,
        resume_text,
        account_key=f"{getattr(state, 'short', row.get('acc', ''))}:{neg_id}:regenerate",
    )
    draft = str(decision.answer or "").strip()
    if not draft:
        raise ValueError(_review_reason(decision))

    reason = _review_reason(decision)
    upsert_interview(
        neg_id,
        acc=str(row.get("acc") or ""), acc_color=str(row.get("acc_color") or ""),
        employer=str(row.get("employer") or ""), vacancy_title=str(row.get("vacancy_title") or ""),
        vacancy_id=str(row.get("vacancy_id") or ""), employer_last_msg=str(row.get("employer_last_msg") or ""),
        needs_reply=True, llm_reply=draft, llm_sent=False, llm_source="llm_regenerated_review",
        llm_category=str(decision.category or "general"), llm_review_reason=reason,
    )
    return _interview_row(neg_id) or {"neg_id": neg_id, "llm_reply": draft}


@router.get("/api/interviews/summary")
async def api_interviews_summary(acc: str = ""):
    return get_interviews_summary(acc=acc)


@router.get("/api/interviews")
async def api_interviews(acc: str = "", limit: int = 2000, status: str = "", redact: bool = False):
    items = get_interviews_list(acc=acc, limit=limit, status=status)
    if not redact:
        return items
    redacted = []
    for item in items:
        copy = dict(item)
        for field in ("llm_reply", "employer_last_msg"):
            val = copy.get(field)
            if isinstance(val, str) and len(val) > 80:
                copy[field] = val[:80] + "…"
        redacted.append(copy)
    return redacted


@router.post("/api/interviews/{neg_id}/regenerate")
async def api_interview_regenerate(neg_id: str):
    try:
        row = await asyncio.to_thread(_regenerate_interview_sync, str(neg_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Не удалось перегенерировать ответ") from exc
    return {"ok": True, "row": row}


@router.get("/api/vacancies")
async def api_vacancies(limit: int = 3000):
    return get_vacancy_db(limit)


@router.delete("/api/vacancy/{vacancy_id}")
async def api_vacancy_delete(vacancy_id: str, account: str = ""):
    """Удалить вакансию из applied и/или test кэша."""
    _load_cache()
    removed = []
    with _cache_lock:
        if account:
            if account in _cache_applied and vacancy_id in _cache_applied[account]:
                del _cache_applied[account][vacancy_id]
                removed.append(f"applied:{account}")
        else:
            for acc_name in list(_cache_applied.keys()):
                if vacancy_id in _cache_applied[acc_name]:
                    del _cache_applied[acc_name][vacancy_id]
                    removed.append(f"applied:{acc_name}")
        if vacancy_id in _cache_tests:
            del _cache_tests[vacancy_id]
            removed.append("test")
    if "applied" in " ".join(removed):
        threading.Thread(target=_save_applied_async, daemon=True).start()
    if "test" in " ".join(removed):
        threading.Thread(target=_save_tests_async, daemon=True).start()
    return {"ok": True, "removed": removed}


@router.get("/api/hr_contacts")
async def api_hr_contacts():
    """Return collected HR contact info from vacancy pre-checks."""
    return {"contacts": list(bot.hr_contacts), "total": len(bot.hr_contacts)}
