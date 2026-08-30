"""Mobile-версия заполнения анкеты при отклике (Phase 3).

Решение Phase 3 (факт из разбора APK ru.hh.android v26.28.1, декомпилят
/tmp/hh-apk/src2/sources): нативного Retrofit-endpoint'а для анкет/опросов
в mobile-приложении НЕТ (grep по @u9-аннотациям с
test/questionnaire/survey/answer нашёл только /survey_user_targeting/
banner_info и /contests/* — не то). При error_type=test_required приложение
показывает alert и открывает WEB-страницу анкеты (applicant/vacancy_response)
в webview. То есть официальное mobile-приложение заполняет анкеты через
web-flow — повторяем эту семантику: делегируем в
hh_apply.fill_and_submit_questionnaire. Cookies hh.ru в acc те же, что
использует web-flow; FallbackHHClient для web-аккаунтов и так ходит в эту
же функцию, так что поведение mobile и web совпадает.
"""

import asyncio

from app import hh_apply


def oauth_web_account_sync(acc: dict) -> dict:
    """Build an ephemeral HH web session from the account's OAuth token.

    The Android app uses the same bridge for WebView-only screens.  Cookies are
    kept only in the returned copy and are never persisted in the OAuth account.
    """
    from app.mobile_auth import HHMobileClient
    from app.oauth import _obtain_oauth_token

    token = _obtain_oauth_token(acc)
    if not token:
        raise RuntimeError("Нет действующего OAuth-токена")
    user_id = str(acc.get("user_id") or "").strip()
    if not user_id:
        counters = HHMobileClient()._request("GET", "me", token=token)
        user_id = str(counters.get("id") or "") if isinstance(counters, dict) else ""
    cookies = HHMobileClient().create_browser_cookies(token, {"id": user_id})
    return {**acc, "cookies": cookies}


async def oauth_web_account(acc: dict) -> dict:
    return await asyncio.to_thread(oauth_web_account_sync, acc)


async def fill_questionnaire(acc: dict, vid: str,
                             vacancy_title: str = "", company: str = "") -> tuple:
    """Заполнить анкету при отклике: делегирование в web-flow.

    Нативного mobile-endpoint'а для анкет нет (см. docstring модуля:
    официальное приложение открывает web-анкету в webview), поэтому
    вызываем hh_apply.fill_and_submit_questionnaire как есть —
    аргументы пробрасываются позиционно, результат возвращается
    без преобразования.

    Возвращает (result, info) web-функции:
    result = sent | limit | test | error | auth_error.
    """
    web_acc = acc
    if str(acc.get("mode") or "").strip().lower() == "oauth":
        try:
            web_acc = await oauth_web_account(acc)
        except Exception as exc:
            return "auth_error", {"error_type": "oauth_autologin_failed", "message": str(exc)}
    return await hh_apply.fill_and_submit_questionnaire(
        web_acc, vid, vacancy_title, company)
