"""Per-execution overrides for outbound apply safety.

Search-only remains globally enabled. A vacancy batch explicitly approved by the
user may bypass only the search-only guard in its worker context; all duplicate,
quota, questionnaire and transport safety checks still run normally.
"""

from __future__ import annotations

from contextvars import ContextVar

from app.config import CONFIG


_APPROVED_SEARCH_APPLY = ContextVar("approved_search_apply", default=False)


def search_only_blocked() -> bool:
    """Return True when outbound applications must be blocked by search-only."""
    return bool(CONFIG.search_only_mode) and not bool(_APPROVED_SEARCH_APPLY.get())


def set_approved_search_apply(enabled: bool) -> None:
    """Enable/disable the narrow search-only bypass in the current context."""
    _APPROVED_SEARCH_APPLY.set(bool(enabled))
