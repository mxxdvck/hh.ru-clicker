"""Project Phase 5E: safe-search vacancy workspace."""

from playwright.sync_api import expect


PREVIEW = [
    {"id": "101", "title": "1C Developer", "company": "Acme", "salary_from": 220000,
     "url": "https://hh.ru/vacancy/101", "source_query": "1C developer",
     "published_at": "2026-09-06T12:00:00+03:00", "schedules": ["remote"],
     "has_test": True, "hr_online": "online", "chat_write_possibility": "ENABLED",
     "quick_responses_allowed": True, "accredited_it_employer": True},
    {"id": "102", "title": "1C ERP Developer", "company": "Beta", "salary_to": 280000,
     "url": "https://hh.ru/vacancy/102"},
]


def _open_workspace(ui, *, ready=True, preview=None):
    acc = ui.state["accounts"][0]
    acc["search_preview"] = list(PREVIEW if preview is None else preview)
    acc["total_vacancies"] = len(acc["search_preview"])
    acc["paused"] = ready
    acc["paused_reason"] = "search_only" if ready else ""
    acc["status"] = "search_only" if ready else "idle"
    ui.state["config"]["search_only_mode"] = True
    ui.open()
    page = ui.page
    page.get_by_test_id("phase5-nav-vacancies").click()
    expect(page.locator("#panel-db")).to_be_visible()
    expect(page.get_by_test_id("phase5-vacancy-workspace")).to_be_visible()
    return page


def test_phase5_vacancy_workspace_renders_safe_shortlist_above_legacy_db(ui):
    page = _open_workspace(ui)

    expect(page.get_by_test_id("phase5-vacancy-0-101")).to_contain_text("1C Developer")
    expect(page.get_by_test_id("phase5-vacancy-0-101")).to_contain_text("прошла фильтры + дедуп")
    expect(page.get_by_test_id("phase5-vacancy-0-101")).to_contain_text("поиск: 1C developer")
    expect(page.get_by_test_id("phase5-vacancy-0-101")).to_contain_text("график: remote")
    expect(page.get_by_test_id("phase5-vacancy-0-101")).to_contain_text("тест / опрос")
    expect(page.get_by_test_id("phase5-vacancy-0-101")).to_contain_text("HR: online")
    expect(page.get_by_test_id("phase5-vacancy-0-101")).to_contain_text("quick response")
    expect(page.locator("#db-panel")).to_be_visible()
    expect(page.get_by_test_id("phase5-vacancy-apply-selected")).to_contain_text("(2)")


def test_phase5_vacancy_bulk_apply_sends_exact_selected_ids_without_new_search(ui):
    page = _open_workspace(ui)
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_test_id("phase5-vacancy-apply-selected").click()

    ui.wait_until(lambda: any(c.get("type") == "apply_search_results" for c in ui.commands))
    commands = [c for c in ui.commands if c.get("type") == "apply_search_results"]
    assert commands == [{"type": "apply_search_results", "idx": 0, "vacancy_ids": ["101", "102"]}]
    assert not any(c.get("type") in {"start", "start_account", "search"} for c in ui.commands)


def test_phase5_vacancy_selection_controls_exact_subset(ui):
    page = _open_workspace(ui)
    row = page.get_by_test_id("phase5-vacancy-0-101")
    row.locator('input[type="checkbox"]').uncheck()
    expect(page.get_by_test_id("phase5-vacancy-apply-selected")).to_contain_text("(1)")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_test_id("phase5-vacancy-apply-selected").click()
    ui.wait_until(lambda: any(c.get("type") == "apply_search_results" for c in ui.commands))
    command = [c for c in ui.commands if c.get("type") == "apply_search_results"][-1]
    assert command["vacancy_ids"] == ["102"]


def test_phase5_vacancy_apply_one_uses_same_safe_subset_command(ui):
    page = _open_workspace(ui)
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_test_id("phase5-vacancy-apply-one-0-102").click()
    ui.wait_until(lambda: any(c.get("type") == "apply_search_results" for c in ui.commands))
    command = [c for c in ui.commands if c.get("type") == "apply_search_results"][-1]
    assert command == {"type": "apply_search_results", "idx": 0, "vacancy_ids": ["102"]}


def test_phase5_vacancy_apply_is_fail_closed_when_safe_list_not_paused(ui):
    page = _open_workspace(ui, ready=False)
    row = page.get_by_test_id("phase5-vacancy-0-101")
    expect(row.locator('input[type="checkbox"]')).to_be_disabled()
    expect(page.get_by_test_id("phase5-vacancy-apply-one-0-101")).to_be_disabled()
    expect(page.get_by_test_id("phase5-vacancy-apply-selected")).to_be_disabled()
    assert not any(c.get("type") == "apply_search_results" for c in ui.commands)


def test_phase5_vacancy_hide_removes_selection_and_can_be_restored(ui):
    page = _open_workspace(ui)
    row = page.get_by_test_id("phase5-vacancy-0-101")
    row.locator("button", has_text="Скрыть").click()
    expect(page.get_by_test_id("phase5-vacancy-apply-selected")).to_contain_text("(1)")
    expect(page.get_by_test_id("phase5-vacancy-0-101")).to_be_hidden()

    page.get_by_test_id("phase5-vacancy-hidden-toggle").click()
    row = page.get_by_test_id("phase5-vacancy-0-101")
    expect(row).to_be_visible()
    row.locator("button", has_text="Вернуть").click()
    expect(page.get_by_test_id("phase5-vacancy-apply-selected")).to_contain_text("(2)")


def test_phase5_vacancy_workspace_refreshes_when_safe_shortlist_changes(ui):
    page = _open_workspace(ui)
    expect(page.get_by_test_id("phase5-vacancy-apply-selected")).to_contain_text("(2)")

    ui.state["accounts"][0]["search_preview"] = [
        {"id": "201", "title": "1C Analyst", "company": "Gamma", "url": "https://hh.ru/vacancy/201"}
    ]
    ui.state["accounts"][0]["total_vacancies"] = 1
    ui.push_state()

    expect(page.get_by_test_id("phase5-vacancy-0-201")).to_be_visible()
    expect(page.get_by_test_id("phase5-vacancy-0-101")).to_have_count(0)
    expect(page.get_by_test_id("phase5-vacancy-apply-selected")).to_contain_text("(1)")


def test_phase5_vacancy_workspace_mobile_primary_action_stays_reachable(ui):
    page = _open_workspace(ui)
    page.set_viewport_size({"width": 390, "height": 844})
    button = page.get_by_test_id("phase5-vacancy-apply-selected")
    button.scroll_into_view_if_needed()
    expect(button).to_be_visible()
    box = button.bounding_box()
    assert box is not None
    assert box["x"] >= 0
    assert box["x"] + box["width"] <= 390


def test_phase5_vacancy_workspace_marks_truncated_preview_and_keeps_full_queue_action(ui):
    preview = [
        {"id": str(1000 + i), "title": f"1C Developer {i}", "company": "Acme",
         "url": f"https://hh.ru/vacancy/{1000 + i}"}
        for i in range(50)
    ]
    page = _open_workspace(ui, preview=preview)
    ui.state["accounts"][0]["total_vacancies"] = 80
    ui.push_state()

    account = page.get_by_test_id("phase5-vacancy-account-0")
    expect(account).to_contain_text("Показаны первые 50 из 80")
    expect(page.get_by_test_id("phase5-vacancy-apply-selected")).to_contain_text("(50)")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_test_id("phase5-vacancy-apply-all-0").click()
    ui.wait_until(lambda: any(c.get("type") == "apply_search_results" for c in ui.commands))
    command = [c for c in ui.commands if c.get("type") == "apply_search_results"][-1]
    assert command == {"type": "apply_search_results", "idx": 0}
    assert "vacancy_ids" not in command
