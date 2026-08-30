"""Native HH Pro server-side auto-response rules (Android 26.32).

Read operations are safe.  Create/update are deliberately exposed as explicit
functions only: importing this module never enables auto-response by itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.hh_mobile_transport import mobile_request


_FILTER_KEYS = {
    "districts",
    "experience",
    "industries",
    "only_with_salary",
    "professional_roles",
    "salary",
}


def _filters(value: dict | None) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("auto-response filters must be an object")
    unknown = set(value) - _FILTER_KEYS
    if unknown:
        raise ValueError(f"unsupported auto-response filters: {sorted(unknown)}")
    return dict(value)


def fetch_rules(acc: dict) -> list[dict]:
    """Return the account's native HH auto-response rules."""
    payload = mobile_request(acc, "GET", "/auto_response/rule")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    items = payload.get("items") or payload.get("auto_responses") or []
    return [item for item in items if isinstance(item, dict)]


def fetch_statistics(acc: dict, rule_id: str, *, days: int = 7) -> dict:
    """Return native counters for a rule; the Android UI defaults to 7 days."""
    rule_id = str(rule_id or "").strip()
    if not rule_id:
        raise ValueError("auto-response rule id is required")
    days = max(1, min(int(days), 365))
    from_date = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    payload = mobile_request(
        acc,
        "GET",
        f"/auto_response/rule/{rule_id}/statistics",
        params={"from_date": from_date},
    )
    return payload if isinstance(payload, dict) else {}


def create_rule(acc: dict, resume_id: str, filters: dict | None = None) -> dict:
    """Create a native rule.  Must only be called after explicit user action."""
    resume_id = str(resume_id or "").strip()
    if not resume_id:
        raise ValueError("resume id is required")
    body = {"resume_id": resume_id}
    clean_filters = _filters(filters)
    if clean_filters is not None:
        body["filters"] = clean_filters
    payload = mobile_request(acc, "POST", "/auto_response/rule", json_body=body)
    return payload if isinstance(payload, dict) else {}


def update_rule(acc: dict, rule_id: str, resume_id: str, *, enabled: bool,
                filters: dict | None = None) -> dict:
    """Update, enable or disable a native rule after explicit user action."""
    rule_id = str(rule_id or "").strip()
    resume_id = str(resume_id or "").strip()
    if not rule_id or not resume_id:
        raise ValueError("rule id and resume id are required")
    body = {"resume_id": resume_id, "enabled": bool(enabled)}
    clean_filters = _filters(filters)
    if clean_filters is not None:
        body["filters"] = clean_filters
    payload = mobile_request(
        acc, "PUT", f"/auto_response/rule/{rule_id}", json_body=body,
    )
    return payload if isinstance(payload, dict) else {}
