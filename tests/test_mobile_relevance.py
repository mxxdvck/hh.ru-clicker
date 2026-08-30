import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE
from app.mobile_relevance import fetch_setka_relevance


ACC = {"name": "a1", "cookies": {}}
URL = MOBILE_BASE + "/setka/vacancy/123/relevance"


@responses.activate
def test_setka_relevance_boolean(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda acc: "token")
    responses.add(responses.GET, URL, json={"relevant": True}, status=200)
    assert fetch_setka_relevance(ACC, "123") is True


@responses.activate
def test_setka_relevance_is_optional(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda acc: "token")
    responses.add(responses.GET, URL, json={"errors": []}, status=404)
    assert fetch_setka_relevance(ACC, "123") is None


@responses.activate
def test_setka_relevance_rejects_unknown_shape(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda acc: "token")
    responses.add(responses.GET, URL, json={"relevant": "yes"}, status=200)
    assert fetch_setka_relevance(ACC, "123") is None
