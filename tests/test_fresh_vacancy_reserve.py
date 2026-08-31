from datetime import datetime, timedelta, timezone

from app.manager import _is_fresh_vacancy, _protect_fresh_batch


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _meta(age_hours, **extra):
    return {
        "published_at": (NOW - timedelta(hours=age_hours)).isoformat(),
        **extra,
    }


def test_fresh_boundary_and_archived_guard():
    assert _is_fresh_vacancy(_meta(2), 24, NOW)
    assert _is_fresh_vacancy(_meta(24), 24, NOW)
    assert not _is_fresh_vacancy(_meta(25), 24, NOW)
    assert not _is_fresh_vacancy(_meta(1, archived=True), 24, NOW)
    assert not _is_fresh_vacancy({}, 24, NOW)
    assert _is_fresh_vacancy({"published_at": "2026-08-30T14:00:00+0300"}, 24, NOW)


def test_old_vacancies_stop_at_reserved_boundary_but_fresh_continue():
    meta = {"old1": _meta(72), "fresh": _meta(1), "old2": _meta(48)}
    selected, deferred = _protect_fresh_batch(
        ["old1", "fresh", "old2"], meta,
        hours=24, ceiling=200, reserve=50, used=149, now=NOW,
    )
    assert selected == ["old1", "fresh"]
    assert deferred == 1


def test_at_boundary_only_fresh_can_consume_reserved_slots():
    meta = {"old": _meta(48), "fresh": _meta(1)}
    selected, deferred = _protect_fresh_batch(
        ["old", "fresh"], meta,
        hours=24, ceiling=200, reserve=50, used=150, now=NOW,
    )
    assert selected == ["fresh"]
    assert deferred == 1


def test_smaller_custom_daily_limit_is_respected():
    meta = {"old": _meta(48)}
    selected, deferred = _protect_fresh_batch(
        ["old"], meta, hours=24, ceiling=100, reserve=50, used=50, now=NOW,
    )
    assert selected == []
    assert deferred == 1


def test_fresh_can_use_last_slot_but_nothing_can_exceed_ceiling():
    meta = {"fresh": _meta(1), "old": _meta(48)}
    selected, deferred = _protect_fresh_batch(
        ["old", "fresh"], meta, hours=24, ceiling=200, reserve=50, used=199, now=NOW,
    )
    assert selected == ["fresh"]
    assert deferred == 1
    selected, deferred = _protect_fresh_batch(
        ["fresh"], meta, hours=24, ceiling=200, reserve=50, used=200, now=NOW,
    )
    assert selected == []
    assert deferred == 1
