"""Personal career-market statistics used by HH Android 26.32."""

from app.hh_mobile_transport import mobile_request


def _id(value) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    return str(value or "")


def fetch_career_radar(acc: dict) -> dict:
    """Return the account profession plus salary/vacancy yearly series."""
    profile = mobile_request(
        acc, "GET", "/career_platform/profile",
        params={"profession_description": "true"},
    )
    if not isinstance(profile, dict):
        return {"ok": False, "error": "career_profile_unavailable"}
    profession = profile.get("profession") or {}
    area = profile.get("area") or {}
    grade = profile.get("grade") or {}
    params = {
        "profession": _id(profession),
        "area_id": _id(area),
        "grade": _id(grade),
    }
    if not all(params.values()):
        return {
            "ok": False, "error": "career_dimensions_missing",
            "profession": profession.get("name", "") if isinstance(profession, dict) else "",
        }
    salary = mobile_request(
        acc, "GET", "/career_platform/statistics/salary/average", params=params)
    vacancies = mobile_request(
        acc, "GET", "/career_platform/statistics/vacancies", params=params)
    salary_series = salary.get("salaries") if isinstance(salary, dict) else []
    vacancy_series = vacancies.get("vacancies") if isinstance(vacancies, dict) else []
    return {
        "ok": True,
        "profession": profession.get("name", "") if isinstance(profession, dict) else "",
        "grade": grade.get("name", "") if isinstance(grade, dict) else "",
        "area_id": params["area_id"],
        "salary": salary_series if isinstance(salary_series, list) else [],
        "vacancies": vacancy_series if isinstance(vacancy_series, list) else [],
    }
