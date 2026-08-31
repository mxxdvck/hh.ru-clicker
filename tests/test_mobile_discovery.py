import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE
from app.mobile_autosearch import delete_autosearch, update_autosearch
from app.mobile_discovery import fetch_bell_notifications, fetch_hidden, restore_hidden


ACC = {"name": "a", "resume_hash": "r1", "cookies": {}}


def _token(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda acc: "token")


@responses.activate
def test_fetch_hidden_combines_two_lists(monkeypatch):
    _token(monkeypatch)
    responses.add(responses.GET, MOBILE_BASE + "/vacancies/blacklisted",
                  json={"found": 1, "items": [{"id": "v1"}]})
    responses.add(responses.GET, MOBILE_BASE + "/employers/blacklisted",
                  json={"found": 2, "items": [{"id": "e1"}], "limit_reached": True})
    result = fetch_hidden(ACC)
    assert result["vacancies_total"] == 1
    assert result["employers_total"] == 2
    assert result["employer_limit_reached"] is True


@responses.activate
def test_restore_hidden_uses_delete(monkeypatch):
    _token(monkeypatch)
    responses.add(responses.DELETE, MOBILE_BASE + "/employers/blacklisted/e1", status=204)
    assert restore_hidden(ACC, "employer", "e1") == {"ok": True}
    assert responses.calls[0].request.method == "DELETE"


def test_restore_hidden_rejects_unknown_kind_without_network():
    assert restore_hidden(ACC, "all", "1") == {"ok": False, "error": "invalid_kind"}


@responses.activate
def test_bell_notifications_shape(monkeypatch):
    _token(monkeypatch)
    responses.add(responses.GET, MOBILE_BASE + "/notifications/bell",
                  json={"notifications": [{"id": "n1", "text": "Hello"}]})
    assert fetch_bell_notifications(ACC)["notifications"][0]["id"] == "n1"


@responses.activate
def test_autosearch_update_and_delete(monkeypatch):
    _token(monkeypatch)
    url = MOBILE_BASE + "/saved_searches/vacancies/s1"
    responses.add(responses.PUT, url, status=204)
    responses.add(responses.DELETE, url, status=204)
    assert update_autosearch(ACC, "s1", name=" Python ")["ok"] is True
    assert delete_autosearch(ACC, "s1") == {"ok": True}
    assert responses.calls[0].request.params == {"name": "Python"}


def test_autosearch_update_requires_changes():
    assert update_autosearch(ACC, "s1") == {"ok": False, "error": "no_changes"}
