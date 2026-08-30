"""Best-effort Setka relevance signal exposed by the HH Android API.

This is *not* a vacancy-to-resume match score. Android uses it in the
employee-referral (Setka) feature and the response contains one boolean:
``{"relevant": true|false}``.
"""

from app.hh_mobile_transport import MobileAPIError, mobile_request
from app.logging_utils import log_debug


def fetch_setka_relevance(acc: dict, vacancy_id: str) -> bool | None:
    """Return Setka relevance, or ``None`` when the optional API is unavailable."""
    try:
        data = mobile_request(acc, "GET", f"/setka/vacancy/{vacancy_id}/relevance")
    except MobileAPIError as exc:
        # This optional signal must never trigger application-flow fallback.
        log_debug(
            f"mobile Setka relevance vacancy={vacancy_id}: "
            f"HTTP {exc.status_code} | {exc.payload}"
        )
        return None
    if not isinstance(data, dict) or not isinstance(data.get("relevant"), bool):
        return None
    return data["relevant"]
