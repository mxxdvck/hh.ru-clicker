import pytest

from app.manager import (
    _dedupe_same_postings, _drop_recently_applied_postings,
    _normalize_title_text, _title_matches_target,
)


INCLUDES = [
    "\u043f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0438\u0441\u0442 1\u0441",
    "\u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a 1\u0441",
    "1\u0441-\u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a",
    "\u0441\u0442\u0430\u0436\u0435\u0440 1\u0441",
    "\u0441\u0442\u0430\u0436\u0451\u0440 1\u0441",
    "junior 1\u0441",
    "junior 1c",
    "\u0441\u0442\u0430\u0436\u0435\u0440-\u043f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0438\u0441\u0442 1\u0441",
    "\u0441\u0442\u0430\u0436\u0451\u0440-\u043f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0438\u0441\u0442 1\u0441",
]
EXCLUDES = [
    "senior", "lead", "team lead", "tech lead", "middle", "\u043c\u0438\u0434\u043b",
    "\u0442\u0438\u043c\u043b\u0438\u0434", "\u0441\u0442\u0430\u0440\u0448\u0438\u0439", "\u0432\u0435\u0434\u0443\u0449\u0438\u0439", "\u0440\u0443\u043a\u043e\u0432\u043e\u0434\u0438\u0442\u0435\u043b\u044c",
    "\u0430\u0440\u0445\u0438\u0442\u0435\u043a\u0442\u043e\u0440", "\u0433\u043b\u0430\u0432\u043d\u044b\u0439", "\u0430\u043d\u0430\u043b\u0438\u0442\u0438\u043a",
]

@pytest.mark.parametrize("title", [
    "\u041f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0438\u0441\u0442 1\u0421",
    "\u041f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0438\u0441\u0442-1\u0421",
    "1\u0421-\u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a",
    "\u0421\u0442\u0430\u0436\u0451\u0440-\u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a 1\u0421",
    "\u041f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0438\u0441\u0442 1\u0421/\u0441\u0442\u0430\u0436\u0435\u0440",
    "\u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a/\u043f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0438\u0441\u0442-\u0441\u0442\u0430\u0436\u0451\u0440 1\u0421",
    "\u041f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0438\u0441\u0442 1\u0421 (junior+/middle/middle+/senior)",
    "Junior 1C developer",
])
def test_targeted_junior_1c_titles_survive_variants(title):
    assert _title_matches_target(title, INCLUDES, EXCLUDES) == (True, "")


@pytest.mark.parametrize(("title", "reason"), [
    ("\u041f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0438\u0441\u0442 1\u0421 (middle)", "excluded"),
    ("Senior \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a 1\u0421", "excluded"),
    ("\u0412\u0435\u0434\u0443\u0449\u0438\u0439 \u043f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0438\u0441\u0442 1\u0421", "excluded"),
    ("\u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a 1\u0421", "no_include"),
    ("\u041f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0438\u0441\u0442-\u0430\u043d\u0430\u043b\u0438\u0442\u0438\u043a 1\u0421", "excluded"),
    ("\u0411\u0443\u0445\u0433\u0430\u043b\u0442\u0435\u0440 1\u0421", "no_include"),
    ("Junior Unity Developer", "no_include"),
    ("Project Manager 1\u0421", "no_include"),
    ("Java \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a \u0432 \u043f\u0440\u043e\u0435\u043a\u0442 \u043d\u0430 1C:Element", "no_include"),
    ("PHP-\u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a (1C \u0411\u0438\u0442\u0440\u0438\u043a\u0441)", "no_include"),
])
def test_non_target_or_senior_titles_stay_blocked(title, reason):
    assert _title_matches_target(title, INCLUDES, EXCLUDES) == (False, reason)


def test_title_normalization_unifies_latin_1c_and_punctuation():
    assert _normalize_title_text("  Junior/1C-Developer ") == "junior 1\u0441 developer"



def test_same_employer_title_candidates_are_deduped():
    ids = ["1", "2", "3", "4"]
    meta = {
        "1": {"title": "Programmer 1C", "company": "Same Co"},
        "2": {"title": "Programmer-1C", "company": "Same Co"},
        "3": {"title": "Programmer 1C", "company": "Other Co"},
        "4": {"title": "Programmer 1C", "company": ""},
    }
    kept, duplicates = _dedupe_same_postings(ids, meta)
    assert kept == ["1", "3", "4"]
    assert duplicates == 1


def test_recent_applied_clone_is_blocked_across_search_cycles(monkeypatch):
    monkeypatch.setattr(
        "app.manager.get_account_applied",
        lambda account_name: {
            "old-id": {
                "title": "Программист 1С (департамент программного обеспечения)",
                "company": "Красное & Белое, розничная сеть",
                "at": "2099-01-01T12:00:00+03:00",
            }
        },
    )
    ids = ["new-clone", "other"]
    meta = {
        "new-clone": {
            "title": "Программист 1С (департамент программного обеспечения)",
            "company": "Красное & Белое, розничная сеть",
        },
        "other": {"title": "Программист 1С", "company": "Другая компания"},
    }
    kept, duplicates = _drop_recently_applied_postings(ids, meta, "acc")
    assert kept == ["other"]
    assert duplicates == 1
