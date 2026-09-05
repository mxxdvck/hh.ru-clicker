from app import oauth
from app.hh_client_mobile import MobileHHClient


ACC = {"resume_hash": "rh", "cookies": {}}


def test_mobile_employer_id_uses_oauth_vacancy_details(monkeypatch):
    calls = []
    monkeypatch.setattr(
        oauth,
        "fetch_vacancy_details",
        lambda acc, vid: (calls.append((acc, vid)) or {"employer_id": "42"}),
    )

    assert MobileHHClient(ACC).fetch_employer_id_for_vacancy(123) == 42
    assert calls == [(ACC, "123")]


def test_mobile_employer_id_handles_missing_or_invalid_value(monkeypatch):
    monkeypatch.setattr(oauth, "fetch_vacancy_details", lambda acc, vid: {})
    assert MobileHHClient(ACC).fetch_employer_id_for_vacancy("123") is None

    monkeypatch.setattr(oauth, "fetch_vacancy_details", lambda acc, vid: {"employer_id": "bad"})
    assert MobileHHClient(ACC).fetch_employer_id_for_vacancy("123") is None


def test_oauth_vacancy_details_exposes_numeric_employer_id(monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "name": "Программист 1С",
                "alternate_url": "https://hh.ru/vacancy/314",
                "employer": {"id": "314", "name": "Acme", "trusted": True},
            }

    monkeypatch.setattr(oauth, "_oauth_headers", lambda acc: {"Authorization": "Bearer x"})
    monkeypatch.setattr(oauth.HH, "get", lambda *args, **kwargs: Response())
    with oauth._vacancy_details_lock:
        oauth._vacancy_details_cache.pop("vacancy-employer-regression", None)

    result = oauth.fetch_vacancy_details(ACC, "vacancy-employer-regression")

    assert result["employer_id"] == 314
    assert result["title"] == "Программист 1С"
    assert result["company"] == "Acme"
    assert result["url"] == "https://hh.ru/vacancy/314"
