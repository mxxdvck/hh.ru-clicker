import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE
from app.mobile_career import fetch_career_radar
from app.mobile_visibility import fetch_resume_visibility


ACC = {"name": "a", "resume_hash": "r1", "cookies": {}}


@responses.activate
def test_career_radar_combines_profile_and_statistics(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda acc: "token")
    responses.add(responses.GET, MOBILE_BASE + "/career_platform/profile", json={
        "profession": {"id": "p1", "name": "Backend"},
        "area": {"id": "1"}, "grade": {"id": "middle", "name": "Middle"},
    })
    responses.add(responses.GET, MOBILE_BASE + "/career_platform/statistics/salary/average",
                  json={"salaries": [{"year": 2026, "salary": 200000}]})
    responses.add(responses.GET, MOBILE_BASE + "/career_platform/statistics/vacancies",
                  json={"vacancies": [{"year": 2026, "vacancy_count": 900}]})

    result = fetch_career_radar(ACC)

    assert result["ok"] is True
    assert result["profession"] == "Backend"
    assert result["salary"][0]["salary"] == 200000
    assert result["vacancies"][0]["vacancy_count"] == 900
    assert responses.calls[1].request.params == {
        "profession": "p1", "area_id": "1", "grade": "middle",
    }


@responses.activate
def test_visibility_marks_restricted_mode(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda acc: "token")
    responses.add(responses.GET, MOBILE_BASE + "/resumes/r1/access_types", json={
        "items": [{"id": "clients", "name": "Всем"},
                  {"id": "whitelist", "name": "Только выбранным", "active": True, "total": 2}],
    })
    responses.add(responses.GET, MOBILE_BASE + "/resumes/r1/blacklist",
                  json={"found": 3, "items": []})
    responses.add(responses.GET, MOBILE_BASE + "/resumes/r1/whitelist",
                  json={"found": 2, "items": []})

    result = fetch_resume_visibility(ACC, "r1")

    assert result["ok"] is True
    assert result["active"]["id"] == "whitelist"
    assert result["warning"] is True
    assert result["blacklist_total"] == 3
    assert result["whitelist_total"] == 2


def test_visibility_requires_resume_id():
    assert fetch_resume_visibility(ACC, "") == {
        "ok": False, "error": "resume_id_required",
    }
