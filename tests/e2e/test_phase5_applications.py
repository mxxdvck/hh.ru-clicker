"""Project Phase 5F: application operations and funnel UI."""

from playwright.sync_api import expect


SUMMARY = {
    "ok": True,
    "account": "Иван Тестов (ivan@example.com)",
    "cycle": {"found": 120, "filtered": 18, "queue": 3, "sent_today": 7, "status": "search_only"},
    "outcome": {"applied": 40, "viewed": 11, "interviews": 5, "conversion_percent": 12.5},
    "ledger": {
        "total": 45,
        "statuses": {
            "applying": 1, "applied": 40, "already": 1,
            "interrupted": 2, "failed_transient": 0, "failed_permanent": 1,
        },
    },
    "sources": {
        "cycle": "current worker snapshot", "applied": "local applied history",
        "viewed": "HH negotiation statistics", "interviews": "local + HH",
        "ledger": "applications.sqlite3",
    },
}


def _open_applications(ui, summary=None, status=200):
    body = SUMMARY if summary is None else summary
    ui.set_response("GET", r"/api/account/0/operations_summary$", body=body, status=status)
    ui.open()
    page = ui.page
    page.get_by_test_id("phase5-nav-applications").click()
    expect(page.locator("#panel-applied")).to_be_visible()
    expect(page.get_by_test_id("phase5-applications-summary")).to_be_visible()
    ui.wait_until(lambda: any(c.get("path") == "/api/account/0/operations_summary" for c in ui.calls))
    return page


def _metric(page, label):
    card = page.locator(".phase5-app-metric", has_text=label).first
    return card.locator(".phase5-app-metric-value")


def test_phase5_applications_separates_cycle_outcome_and_reliability(ui):
    page = _open_applications(ui)

    expect(_metric(page, "Найдено")).to_have_text("120")
    expect(_metric(page, "Прошло фильтры")).to_have_text("18")
    expect(_metric(page, "Safe queue")).to_have_text("3")
    expect(_metric(page, "Отправлено сегодня")).to_have_text("7")
    expect(_metric(page, "Отклики")).to_have_text("40")
    expect(_metric(page, "Просмотрено HH")).to_have_text("11")
    expect(_metric(page, "Интервью")).to_have_text("5")
    expect(_metric(page, "Конверсия")).to_have_text("12.5%")
    expect(_metric(page, "Interrupted")).to_have_text("2")
    expect(_metric(page, "Permanent fail")).to_have_text("1")
    expect(page.get_by_test_id("phase5-app-data-note")).to_contain_text("разные окна данных")
    expect(page.locator("#applied-panel")).to_be_visible()


def test_phase5_applications_keeps_unknown_hh_views_as_no_data(ui):
    summary = {**SUMMARY, "outcome": {**SUMMARY["outcome"], "viewed": None}}
    page = _open_applications(ui, summary=summary)

    expect(_metric(page, "Просмотрено HH")).to_have_text("нет данных")


def test_phase5_applications_does_not_refetch_on_each_snapshot(ui):
    page = _open_applications(ui)

    def calls():
        return [c for c in ui.calls if c.get("path") == "/api/account/0/operations_summary"]

    ui.wait_until(lambda: len(calls()) == 1)
    for found in (43, 44, 45):
        ui.state["global_stats"]["total_found"] = found
        ui.push_state()
    page.wait_for_timeout(150)
    assert len(calls()) == 1


def test_phase5_applications_manual_refresh_refetches_summary(ui):
    page = _open_applications(ui)

    def calls():
        return [c for c in ui.calls if c.get("path") == "/api/account/0/operations_summary"]

    ui.wait_until(lambda: len(calls()) == 1)
    page.get_by_test_id("phase5-app-refresh").click()
    ui.wait_until(lambda: len(calls()) == 2)


def test_phase5_applications_hides_partial_totals_when_summary_fails(ui):
    page = _open_applications(ui, summary={"ok": False, "error": "boom"}, status=500)

    ui.wait_until(lambda: "Не удалось загрузить" in page.get_by_test_id("phase5-app-data-note").inner_text())
    expect(_metric(page, "Найдено")).to_have_text("нет данных")
    expect(_metric(page, "Отклики")).to_have_text("нет данных")
    expect(page.get_by_test_id("phase5-app-data-note")).to_contain_text("Агрегированные значения скрыты")


def test_phase5_applications_mobile_controls_and_legacy_table_remain_reachable(ui):
    page = _open_applications(ui)
    page.set_viewport_size({"width": 390, "height": 844})

    refresh = page.get_by_test_id("phase5-app-refresh")
    refresh.scroll_into_view_if_needed()
    expect(refresh).to_be_visible()
    box = refresh.bounding_box()
    assert box is not None
    assert box["x"] >= 0
    assert box["x"] + box["width"] <= 390
    expect(page.locator("#applied-panel")).to_be_visible()
    assert ui.page_errors == []
