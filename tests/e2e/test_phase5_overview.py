"""Project Phase 5D: operational overview, persisted attention and account health."""

from playwright.sync_api import expect


def _open_overview(ui):
    ui.open()
    page = ui.page
    expect(page.get_by_test_id("phase5-overview")).to_be_visible()
    expect(page.get_by_test_id("phase5-action-center")).to_be_visible()
    expect(page.get_by_test_id("phase5-account-health")).to_be_visible()
    return page


def _kpi_value(page, key):
    return page.get_by_test_id(f"phase5-kpi-{key}").locator(".phase5-kpi-value")


def test_phase5_overview_renders_first_and_followup_snapshots_without_pageerror(ui):
    page = _open_overview(ui)

    expect(_kpi_value(page, "today")).to_have_text("7")
    expect(_kpi_value(page, "found")).to_have_text("42")
    expect(page.get_by_test_id("phase5-overview-mode")).to_contain_text("Только безопасный поиск")

    ui.state["accounts"][0]["daily_sent"] = 8
    ui.state["accounts"][0]["sent"] = 8
    ui.state["global_stats"]["total_found"] = 51
    ui.push_state()

    expect(_kpi_value(page, "today")).to_have_text("8")
    expect(_kpi_value(page, "run")).to_have_text("8")
    expect(_kpi_value(page, "found")).to_have_text("51")
    assert ui.page_errors == []


def test_phase5_overview_persisted_review_survives_empty_live_llm_log(ui):
    ui.state["llm_log"] = []
    ui.data["interviews_summary"] = {
        "total": 3,
        "drafts": 2,
        "reviews": 2,
        "pending": 0,
        "replied": 1,
    }
    page = _open_overview(ui)

    expect(_kpi_value(page, "review")).to_have_text("2")
    review = page.locator("[data-action-key='review']")
    expect(review).to_be_visible()
    expect(review).to_contain_text("2 ответов требуют проверки")


def test_phase5_overview_does_not_invent_filtered_total(ui):
    page = _open_overview(ui)
    expect(_kpi_value(page, "filtered")).to_have_text("нет данных")
    expect(page.get_by_test_id("phase5-kpi-filtered")).to_contain_text("не доказуем")


def test_phase5_overview_attention_links_cookies_to_connection_settings(ui):
    ui.state["accounts"][0]["cookies_expired"] = True
    page = _open_overview(ui)

    item = page.locator("[data-action-key='cookies-0']")
    expect(item).to_be_visible()
    expect(item).to_have_attribute("data-severity", "high")
    item.locator("button").click()

    expect(page.locator("#panel-settings")).to_be_visible()
    expect(page.get_by_test_id("phase5-settings-group-connection")).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(page.locator("#proxy-section")).to_be_visible()


def test_phase5_overview_review_summary_is_not_fetched_on_every_snapshot(ui):
    page = _open_overview(ui)
    page.wait_for_function("window.HHUI && HHUI.overview && HHUI.overview.getReviewSummary() !== null")

    def summary_calls():
        return [
            call for call in ui.calls
            if call.get("method") == "GET" and call.get("path") == "/api/interviews/summary"
        ]

    assert len(summary_calls()) == 1
    for found in (43, 44, 45):
        ui.state["global_stats"]["total_found"] = found
        ui.push_state()
    expect(_kpi_value(page, "found")).to_have_text("45")
    assert len(summary_calls()) == 1


def test_phase5_overview_account_health_is_compact_and_mobile_reachable(ui):
    page = _open_overview(ui)
    health = page.get_by_test_id("phase5-health-account-0")
    expect(health).to_be_visible()
    expect(health).to_contain_text("Иван Тестов")
    expect(health).to_contain_text("Сегодня: 7 / 20")

    page.set_viewport_size({"width": 390, "height": 844})
    button = health.locator("button", has_text="Открыть управление")
    button.scroll_into_view_if_needed()
    expect(button).to_be_visible()
    box = button.bounding_box()
    assert box is not None
    assert box["x"] < 390
    assert box["x"] + box["width"] > 0
