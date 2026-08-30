from datetime import datetime, timedelta, timezone

from app import oauth


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_today_count_does_not_count_old_items_when_tzdata_is_unavailable(monkeypatch):
    msk = timezone(timedelta(hours=3))
    now = datetime.now(msk)
    old = now - timedelta(days=2)
    pages = [
        _Response({
            "found": 500,
            "items": [
                {"created_at": now.isoformat()},
                {"created_at": old.isoformat()},
            ],
        }),
    ]

    monkeypatch.setattr(oauth, "_oauth_headers", lambda acc: {"Authorization": "Bearer token"})
    monkeypatch.setattr(oauth.HH, "get", lambda *args, **kwargs: pages.pop(0))
    oauth._negotiations_count_cache.clear()

    result = oauth.fetch_negotiations_today_count({"resume_hash": "tz-regression"})

    assert result["today"] == 1
    assert result["total_found"] == 500


def test_today_count_accepts_hh_compact_timezone_and_requests_creation_order(monkeypatch):
    msk = timezone(timedelta(hours=3))
    now = datetime.now(msk)
    compact = now.strftime("%Y-%m-%dT%H:%M:%S%z")
    calls = []

    monkeypatch.setattr(oauth, "_oauth_headers", lambda acc: {"Authorization": "Bearer token"})

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _Response({"found": 1, "items": [{"created_at": compact}]})
        return _Response({"found": 1, "items": []})

    monkeypatch.setattr(oauth.HH, "get", fake_get)
    oauth._negotiations_count_cache.clear()
    result = oauth.fetch_negotiations_today_count(
        {"resume_hash": "compact-timezone"}, force=True
    )

    assert result["today"] == 1
    assert calls[0]["params"]["order_by"] == "created_at"


def test_force_bypasses_cached_today_count(monkeypatch):
    monkeypatch.setattr(oauth, "_oauth_headers", lambda acc: {"Authorization": "Bearer token"})
    oauth._negotiations_count_cache.clear()
    oauth._negotiations_count_cache["force-count"] = (
        float("inf"), {"today": 99, "msk_date": "cached", "total_found": 99}
    )
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        return _Response({"found": 0, "items": []})

    monkeypatch.setattr(oauth.HH, "get", fake_get)
    result = oauth.fetch_negotiations_today_count(
        {"resume_hash": "force-count"}, force=True
    )
    assert calls
    assert result["today"] == 0
