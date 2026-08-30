import responses
import pytest

from app.hh_client_mobile import MobileHHClient
from app.hh_mobile_transport import MOBILE_BASE


ACC = {"resume_hash": "rh"}


@pytest.fixture(autouse=True)
def oauth_token(monkeypatch):
    monkeypatch.setattr("app.oauth._obtain_oauth_token", lambda acc: "token")


@responses.activate
def test_fetch_rules_and_seven_day_statistics():
    responses.get(MOBILE_BASE + "/auto_response/rule", json={
        "items": [{"auto_response_id": "a1", "enabled": True}],
    })
    responses.get(MOBILE_BASE + "/auto_response/rule/a1/statistics", json={
        "counters": {"total": 12, "invitation": 2, "vacancy_from_search_count": 30},
    })
    client = MobileHHClient(ACC)

    assert client.fetch_auto_response_rules()[0]["auto_response_id"] == "a1"
    assert client.fetch_auto_response_statistics("a1")["counters"]["total"] == 12
    assert "from_date=" in responses.calls[1].request.url


@responses.activate
def test_create_and_disable_rule_use_android_contract():
    responses.post(MOBILE_BASE + "/auto_response/rule", json={"auto_response_id": "a1"})
    responses.put(MOBILE_BASE + "/auto_response/rule/a1", json={"enabled": False})
    client = MobileHHClient(ACC)
    filters = {"professional_roles": ["96"], "only_with_salary": True}

    assert client.create_auto_response_rule("r1", filters)["auto_response_id"] == "a1"
    assert client.update_auto_response_rule("a1", "r1", enabled=False)["enabled"] is False
    assert responses.calls[0].request.body == (
        b'{"resume_id": "r1", "filters": {"professional_roles": ["96"], '
        b'"only_with_salary": true}}'
    )
    assert responses.calls[1].request.body == b'{"resume_id": "r1", "enabled": false}'


def test_rule_validation_rejects_unknown_filters_without_network():
    with pytest.raises(ValueError, match="unsupported"):
        MobileHHClient(ACC).create_auto_response_rule("r1", {"magic": True})
