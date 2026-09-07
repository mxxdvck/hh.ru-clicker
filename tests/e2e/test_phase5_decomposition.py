"""Project Phase 5H: incremental frontend decomposition contracts."""

from playwright.sync_api import expect


def _counter_calls(ui):
    return [
        call for call in ui.calls
        if call["method"] == "GET" and call["path"].endswith("/counters_v2")
    ]


def test_phase5_counters_use_snapshot_event_without_renderheader_monkey_patch(ui):
    ui.set_response(
        "GET", r"/api/account/0/counters_v2$",
        body={
            "ok": True,
            "counters": {
                "unread_chats": 2,
                "unread_negotiations": 3,
                "new_resume_views": 4,
                "new_notifications": 5,
            },
        },
    )
    ui.open()

    counters = ui.page.locator("#feat4-counters")
    expect(counters).to_be_visible()
    expect(counters).to_contain_text("2")
    expect(counters).to_contain_text("5")
    assert ui.page.evaluate("() => !!(window.renderHeader && window.renderHeader.__feat4Wrapped)") is False


def test_phase5_account_card_features_use_event_bridge(ui):
    ui.set_response(
        "GET", r"/api/account/0/mode$",
        body={"ok": True, "mode": "mobile", "effective_client": "MobileHHClient"},
    )
    ui.open()

    expect(ui.page.locator("#feat3-skills-0")).to_be_visible()
    badge = ui.page.locator("#feat7-mode-badge-0")
    expect(badge).to_be_visible()
    expect(badge).to_have_text("MOBILE")


def test_phase5_mode_settings_decorate_from_tab_event(ui):
    ui.set_response(
        "GET", r"/api/account/0/mode$",
        body={"ok": True, "mode": "web", "effective_client": "web"},
    )
    ui.open()
    ui.page.get_by_test_id("phase5-nav-settings").click()

    rows = ui.page.locator("#acc-cookies-list .feat7-mode-row")
    expect(rows).to_have_count(1)
    expect(rows.locator("select")).to_have_value("web")
