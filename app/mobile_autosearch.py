"""Manage vacancy autosearches using the Android 26.32 contract."""

from app.hh_mobile_transport import mobile_request
from app.oauth import fetch_saved_vacancy_searches


def fetch_autosearches(acc: dict) -> dict:
    return {"ok": True, "items": fetch_saved_vacancy_searches(acc)}


def update_autosearch(acc: dict, search_id: str, *, name=None,
                      email_subscription=None) -> dict:
    params = {}
    if isinstance(name, str) and name.strip():
        params["name"] = name.strip()[:120]
    if isinstance(email_subscription, bool):
        params["email_subscription"] = str(email_subscription).lower()
    if not params:
        return {"ok": False, "error": "no_changes"}
    mobile_request(acc, "PUT", f"/saved_searches/vacancies/{search_id}", params=params)
    return {"ok": True}


def delete_autosearch(acc: dict, search_id: str) -> dict:
    mobile_request(acc, "DELETE", f"/saved_searches/vacancies/{search_id}")
    return {"ok": True}
