"""Applicant utility APIs found in HH Android: hidden lists and bell feed."""

from app.hh_mobile_transport import mobile_request


def _page(acc: dict, path: str) -> dict:
    data = mobile_request(acc, "GET", path, params={"page": 0, "per_page": 50})
    return data if isinstance(data, dict) else {"items": []}


def fetch_hidden(acc: dict) -> dict:
    vacancies = _page(acc, "/vacancies/blacklisted")
    employers = _page(acc, "/employers/blacklisted")
    return {
        "ok": True,
        "vacancies": vacancies.get("items") or [],
        "vacancies_total": int(vacancies.get("found") or 0),
        "employers": employers.get("items") or [],
        "employers_total": int(employers.get("found") or 0),
        "employer_limit_reached": bool(employers.get("limit_reached")),
    }


def restore_hidden(acc: dict, kind: str, object_id: str) -> dict:
    if kind not in {"vacancy", "employer"}:
        return {"ok": False, "error": "invalid_kind"}
    noun = "vacancies" if kind == "vacancy" else "employers"
    mobile_request(acc, "DELETE", f"/{noun}/blacklisted/{object_id}")
    return {"ok": True}


def fetch_bell_notifications(acc: dict) -> dict:
    data = mobile_request(acc, "GET", "/notifications/bell")
    if not isinstance(data, dict):
        return {"ok": True, "notifications": []}
    items = data.get("notifications")
    return {"ok": True, "notifications": items if isinstance(items, list) else []}
