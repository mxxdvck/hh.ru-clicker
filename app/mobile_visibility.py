"""Read-only resume visibility diagnostics from the HH Android API."""

from app.hh_mobile_transport import mobile_request


RISKY_ACCESS_TYPES = {"no_one", "whitelist"}


def fetch_resume_visibility(acc: dict, resume_id: str) -> dict:
    resume_id = str(resume_id or "").strip()
    if not resume_id:
        return {"ok": False, "error": "resume_id_required"}
    access = mobile_request(
        acc, "GET", f"/resumes/{resume_id}/access_types",
        params={"long_period": "true"},
    )
    black = mobile_request(
        acc, "GET", f"/resumes/{resume_id}/blacklist",
        params={"page": 0, "per_page": 20},
    )
    white = mobile_request(
        acc, "GET", f"/resumes/{resume_id}/whitelist",
        params={"page": 0, "per_page": 20},
    )
    items = access.get("items") if isinstance(access, dict) else []
    if not isinstance(items, list):
        items = []
    active = next((x for x in items if isinstance(x, dict) and x.get("active")), {})
    active_id = str(active.get("id") or "")
    return {
        "ok": True,
        "active": {"id": active_id, "name": str(active.get("name") or "")},
        "access_types": [
            {k: x.get(k) for k in ("id", "name", "active", "total", "limit") if k in x}
            for x in items if isinstance(x, dict)
        ],
        "blacklist_total": int(black.get("found") or 0) if isinstance(black, dict) else 0,
        "whitelist_total": int(white.get("found") or 0) if isinstance(white, dict) else 0,
        "warning": active_id in RISKY_ACCESS_TYPES,
    }
