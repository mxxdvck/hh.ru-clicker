"""
Manual vacancy apply flow (two-step: check + submit).
"""

import json
import re

import aiohttp
from fastapi import APIRouter
from glom import glom

from app.logging_utils import _is_login_page
from app.config import CONFIG, hh_base, resolve_letter_text
from app.apply_mode import search_only_blocked
from app.hh_api import get_headers
from app.hh_client_factory import get_client
from app.hh_client_fallback import FallbackHHClient
from app.questionnaire import _parse_questionnaire_rich, suggest_questionnaire_value
from app.instances import bot
from app.user_agent import webview_user_agent
from app.hh_apply import _aio_egress_kwargs
from app.mobile_questionnaire import oauth_web_account
from app.apply_safety import reserve_apply, finalize_apply


router = APIRouter()


async def _fetch_questionnaire_data(acc: dict, vid: str) -> dict:
    """
    Получает форму опросника и возвращает список вопросов с полями.
    НЕ отправляет отклик.
    """
    headers = {
        "User-Agent": webview_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"{hh_base()}/vacancy/{vid}",
    }
    url_form = f"{hh_base()}/applicant/vacancy_response?vacancyId={vid}&withoutTest=no"
    sess_kw, req_kw = _aio_egress_kwargs()
    async with aiohttp.ClientSession(cookies=acc["cookies"], headers=headers, **sess_kw) as session:
        async with session.get(url_form, timeout=aiohttp.ClientTimeout(total=15), **req_kw) as r:
            html = await r.text()
            if r.status in (401, 403) or _is_login_page(html):
                return {"questions": [], "hidden": {}, "error": "auth"}

    hidden = dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html))
    hidden.update(dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]+type="hidden"[^>]+value="([^"]*)"', html)))

    # Reuse the canonical BeautifulSoup parser.  The former route-local regex
    # parser had drifted: radio labels were looked up by value instead of id,
    # and select fields were silently omitted.
    questions = _parse_questionnaire_rich(html)
    for question in questions:
        question["suggested"] = suggest_questionnaire_value(question)

    return {"questions": questions, "hidden": hidden, "url_form": url_form}


async def _web_acc_for_form(acc: dict) -> dict:
    """Use OAuth autologin cookies for WebView-only forms without persisting them."""
    if str(acc.get("mode") or "").strip().lower() == "oauth":
        return await oauth_web_account(acc)
    return acc


def _result_to_response(result: str, info: dict, vid: str,
                        questions: list = None, letter: str = "") -> dict:
    """
    Чистый маппинг tuple (result, info) из client.submit_response() в ответ
    /api/apply/submit. Без I/O и bookkeeping — unit-тестируемо.

    Для result="test" вопросы/letter передаёт вызывающий: их сбор требует
    async-запроса (_fetch_questionnaire_data) и в чистую функцию не входит.
    """
    if result == "sent":
        return {"status": "sent", "vacancy_id": vid, "message": "Отклик успешно отправлен ✅"}
    if result == "limit":
        return {"status": "limit", "vacancy_id": vid, "message": "Достигнут дневной лимит откликов"}
    if result == "already":
        return {"status": "already", "vacancy_id": vid, "message": "Отклик на эту вакансию уже был отправлен"}
    if result == "test":
        questions = questions if questions is not None else []
        return {
            "status": "test_required",
            "vacancy_id": vid,
            "questions": questions,
            "letter": letter,
            "message": f"Вакансия требует опрос ({len(questions)} вопросов)",
        }
    if result == "auth_error":
        return {"status": "error", "vacancy_id": vid, "message": "⚠️ Куки протухли — обновите в настройках"}
    # "error" и любые неизвестные result'ы
    message = str(info.get("error_type") or info.get("exception") or info.get("raw") or "Ошибка отклика")
    return {"status": "error", "vacancy_id": vid, "message": message}


async def _mobile_submit_response(acc_idx: int, acc: dict, vid: str, client) -> dict:
    """Send one already-reserved mobile application and finalize its ledger entry."""
    result, info = await client.submit_response(vid)
    info = info or {}
    state = bot._get_apply_state(acc_idx)
    resume_id = str(acc.get("resume_hash", "") or "")
    finalize_apply(acc.get("name", ""), vid, resume_id, result, info, state=state)

    if result == "sent":
        short = state.short if state else acc.get("name", "?")
        color = state.color if state else ""
        bot._add_log(short, color, f"\U0001f4dd \u0420\u0443\u0447\u043d\u043e\u0439 \u043e\u0442\u043a\u043b\u0438\u043a (mobile): {vid}", "success")

    questions = None
    if result == "test":
        qdata = await _fetch_questionnaire_data(await _web_acc_for_form(acc), vid)
        questions = qdata["questions"]

    return _result_to_response(result, info, vid, questions=questions, letter=acc.get("letter", ""))


@router.post("/api/apply/check")
async def api_apply_check(body: dict):
    """
    Шаг 1: проверяет вакансию — можно ли откликнуться, требует ли опрос.
    """
    try:
        acc_idx = int(body.get("account_idx", 0))
    except (ValueError, TypeError):
        return {"status": "error", "message": "account_idx must be an integer"}
    raw = body.get("vacancy_id", "").strip()
    m = re.search(r'/vacancy/(\d+)', raw) or re.match(r'^(\d+)$', raw)
    if not m:
        return {"status": "error", "message": "Не удалось определить ID вакансии"}
    vid = m.group(1)

    acc = bot._get_apply_acc(acc_idx)
    if acc is None:
        return {"status": "error", "message": "Неверный аккаунт"}

    custom_letter = body.get("letter", "").strip()
    if custom_letter:
        acc["letter"] = custom_letter

    if not acc.get("letter"):
        acc["letter"] = resolve_letter_text(acc)

    try:
        acc = await _web_acc_for_form(acc)
    except Exception as exc:
        return {"status": "error", "vacancy_id": vid, "message": f"OAuth autologin: {exc}"}

    state = bot._get_apply_state(acc_idx)
    resume_id = str(acc.get("resume_hash", "") or "")
    decision = reserve_apply(acc.get("name", ""), vid, resume_id,
                             state=state, source="manual_check")
    if not decision.allowed:
        status = "already" if decision.code == "already" else "blocked"
        return {"status": status, "vacancy_id": vid, "reason": decision.code,
                "message": decision.message}

    sess_kw, req_kw = _aio_egress_kwargs()
    try:
        async with aiohttp.ClientSession(
            cookies=acc["cookies"],
            headers=get_headers(acc.get("cookies", {}).get("_xsrf", "")),
            **sess_kw
        ) as session:
            data = aiohttp.FormData()
            for k, v in [("resume_hash", acc["resume_hash"]), ("vacancy_id", vid),
                         ("letter", acc["letter"]), ("lux", "true"), ("ignore_postponed", "true")]:
                data.add_field(k, v)
            if search_only_blocked():
                finalize_apply(acc.get("name", ""), vid, resume_id, "error",
                               {"error_type": "search_only", "raw": "manual_check runtime search-only guard"}, state=None)
                return {"status": "blocked", "vacancy_id": vid, "reason": "search_only",
                        "message": "Search-only mode: application sending is disabled"}
            async with session.post(
                hh_base() + "/applicant/vacancy_response/popup",
                data=data, timeout=aiohttp.ClientTimeout(total=10), **req_kw
            ) as r:
                txt = await r.text()
                status_code = r.status

        if status_code in (401, 403) or (status_code == 200 and _is_login_page(txt)):
            finalize_apply(acc.get("name", ""), vid, resume_id, "auth_error", {}, state=None)
            return {"status": "error", "vacancy_id": vid, "message": "⚠️ Куки протухли — обновите в настройках"}

        if status_code == 200:
            info = {}
            if "shortVacancy" in txt:
                try:
                    p = json.loads(txt)
                    info = {
                        "title": glom(p, "responseStatus.shortVacancy.name", default=""),
                        "company": glom(p, "responseStatus.shortVacancy.company.name", default=""),
                    }
                except Exception:
                    pass
            finalize_apply(acc.get("name", ""), vid, resume_id, "sent", info, state=state)
            return {"status": "sent", "vacancy_id": vid, **info,
                    "message": "Отклик уже отправлен (без опроса)"}

        if "negotiations-limit-exceeded" in txt:
            finalize_apply(acc.get("name", ""), vid, resume_id, "limit", {}, state=None)
            return {"status": "limit", "vacancy_id": vid, "message": "Достигнут дневной лимит откликов"}

        if "alreadyApplied" in txt:
            finalize_apply(acc.get("name", ""), vid, resume_id, "already", {}, state=None)
            return {"status": "already", "vacancy_id": vid, "message": "Отклик на эту вакансию уже был отправлен"}

        if "test-required" in txt:
            finalize_apply(acc.get("name", ""), vid, resume_id, "test", {}, state=None)
            qdata = await _fetch_questionnaire_data(acc, vid)
            return {
                "status": "test_required",
                "vacancy_id": vid,
                "questions": qdata["questions"],
                "letter": acc["letter"],
                "message": f"Вакансия требует опрос ({len(qdata['questions'])} вопросов)",
            }

        final_info = {"raw": f"HTTP {status_code}: {txt[:100]}", "http_status": status_code}
        if status_code >= 500:
            final_info["transient"] = True
        else:
            final_info["error_type"] = "manual_recoverable"
        finalize_apply(acc.get("name", ""), vid, resume_id, "error", final_info, state=None)
        return {"status": "error", "vacancy_id": vid, "message": f"HTTP {status_code}: {txt[:100]}"}

    except Exception as e:
        finalize_apply(acc.get("name", ""), vid, resume_id, "error",
                       {"exception": str(e), "transient": True}, state=None)
        return {"status": "error", "message": str(e)}


@router.post("/api/apply/submit")
async def api_apply_submit(body: dict):
    """
    Шаг 2: отправляет отклик с заполненными ответами на опрос.
    """
    try:
        acc_idx = int(body.get("account_idx", 0))
    except (ValueError, TypeError):
        return {"status": "error", "message": "account_idx must be an integer"}
    vid = str(body.get("vacancy_id", "")).strip()
    letter = body.get("letter", "")
    user_answers = body.get("answers", {})

    acc = bot._get_apply_acc(acc_idx)
    if acc is None:
        return {"status": "error", "message": "Неверный аккаунт"}
    if letter:
        acc = {**acc, "letter": letter}

    if not acc.get("letter"):
        acc = {**acc, "letter": resolve_letter_text(acc)}

    # Phase 3: mobile-ветка — отклик БЕЗ анкеты через HHClient-фабрику.
    # Маркер mobile-режима: isinstance(client, FallbackHHClient) — фабрика
    # возвращает её только при mode="mobile" (выбрано перед
    # getattr(client, "mode", "") == "mobile": тип строже duck-typed атрибута).
    # Если user_answers непустой (анкета) или режим web — НИЧЕГО не меняется:
    # анкеты — территория web-flow (официальное приложение тоже ходит в них
    # через webview), поэтому web-form flow ниже сохраняется байт-в-байт.
    state = bot._get_apply_state(acc_idx)
    resume_id = str(acc.get("resume_hash", "") or "")
    decision = reserve_apply(acc.get("name", ""), vid, resume_id,
                             state=state, source="manual_submit")
    if not decision.allowed:
        status = "already" if decision.code == "already" else "blocked"
        return {"status": status, "vacancy_id": vid, "reason": decision.code,
                "message": decision.message}

    client = get_client(acc)
    native_oauth = str(acc.get("mode", "")).strip().lower() == "oauth"
    if (isinstance(client, FallbackHHClient) or native_oauth) and not user_answers:
        try:
            return await _mobile_submit_response(acc_idx, acc, vid, client)
        except Exception as e:
            finalize_apply(acc.get("name", ""), vid, resume_id, "error",
                           {"exception": str(e), "transient": True}, state=None)
            return {"status": "error", "message": str(e)}

    if native_oauth:
        try:
            acc = await _web_acc_for_form(acc)
        except Exception as exc:
            finalize_apply(acc.get("name", ""), vid, resume_id, "auth_error",
                           {"exception": str(exc)}, state=None)
            return {"status": "error", "message": f"OAuth autologin: {exc}"}

    url_form = f"{hh_base()}/applicant/vacancy_response?vacancyId={vid}&withoutTest=no"

    sess_kw, req_kw = _aio_egress_kwargs()
    try:
        async with aiohttp.ClientSession(
            cookies=acc["cookies"],
            headers={"User-Agent": webview_user_agent(),
                     "Accept": "text/html,*/*", "Referer": f"{hh_base()}/vacancy/{vid}"},
            **sess_kw
        ) as session:
            async with session.get(url_form, timeout=aiohttp.ClientTimeout(total=15), **req_kw) as r:
                html = await r.text()
                if r.status in (401, 403) or _is_login_page(html):
                    finalize_apply(acc.get("name", ""), vid, resume_id, "auth_error", {}, state=None)
                    return {"status": "error", "message": "⚠️ Куки протухли — обновите в настройках"}
                if r.status == 429:
                    finalize_apply(acc.get("name", ""), vid, resume_id, "limit",
                                   {"http_status": r.status}, state=None)
                    return {"status": "limit", "message": "Достигнут лимит запросов HH"}
                if r.status != 200:
                    info = {"http_status": r.status, "raw": f"questionnaire GET HTTP {r.status}"}
                    if r.status >= 500:
                        info["transient"] = True
                    else:
                        info["error_type"] = "manual_recoverable"
                    finalize_apply(acc.get("name", ""), vid, resume_id, "error", info, state=None)
                    return {"status": "error", "message": f"HTTP {r.status} при загрузке формы"}

            hidden = dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html))
            hidden.update(dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]+type="hidden"[^>]+value="([^"]*)"', html)))

            form = aiohttp.FormData()
            form.add_field("resume_hash", acc["resume_hash"])
            form.add_field("vacancy_id", vid)
            form.add_field("letter", acc["letter"])
            form.add_field("lux", "true")
            for name in ("_xsrf", "uidPk", "guid", "startTime", "testRequired"):
                if name in hidden:
                    form.add_field(name, hidden[name])
            for name, value in user_answers.items():
                # HH checkbox groups expect repeated fields, not a Python-list
                # string such as "['a', 'b']".
                if isinstance(value, list):
                    for item in value:
                        form.add_field(name, str(item))
                else:
                    form.add_field(name, str(value))

            if search_only_blocked():
                finalize_apply(acc.get("name", ""), vid, resume_id, "error",
                               {"error_type": "search_only", "raw": "manual_submit runtime search-only guard"}, state=None)
                return {"status": "blocked", "vacancy_id": vid, "reason": "search_only",
                        "message": "Search-only mode: application sending is disabled"}
            async with session.post(
                url_form,
                headers={"X-Xsrftoken": acc.get("cookies", {}).get("_xsrf", ""), "Referer": url_form},
                data=form,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=False,
                **req_kw
            ) as r2:
                status = r2.status
                location = r2.headers.get("location", "")

        if status in (302, 303):
            if "negotiations-limit-exceeded" in location:
                finalize_apply(acc.get("name", ""), vid, resume_id, "limit", {}, state=None)
                return {"status": "limit", "message": "Достигнут лимит откликов"}
            if "withoutTest=no" in location or f"vacancyId={vid}" in location:
                finalize_apply(acc.get("name", ""), vid, resume_id, "error",
                               {"error_type": "questionnaire_validation",
                                "raw": "questionnaire form rejected"}, state=None)
                return {"status": "error", "message": "Форма не принята — возможно не все вопросы заполнены"}
            state = bot._get_apply_state(acc_idx)
            finalize_apply(acc.get("name", ""), vid, resume_id, "sent", {},
                           state=state, questionnaire=True)
            short = state.short if state else acc.get("name", "?")
            color = state.color if state else ""
            bot._add_log(short, color, f"\U0001f4dd Ручной отклик (опрос): {vid}", "success")
            return {"status": "sent", "message": "Отклик успешно отправлен ✅"}

        final_info = {"raw": f"HTTP {status}", "http_status": status}
        if status >= 500:
            final_info["transient"] = True
        else:
            final_info["error_type"] = "questionnaire_validation"
        finalize_apply(acc.get("name", ""), vid, resume_id, "error", final_info, state=None)
        return {"status": "error", "message": f"HTTP {status}"}

    except Exception as e:
        finalize_apply(acc.get("name", ""), vid, resume_id, "error",
                       {"exception": str(e), "transient": True}, state=None)
        return {"status": "error", "message": str(e)}
