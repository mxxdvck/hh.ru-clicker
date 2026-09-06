"""Project Phase 5C: searchable settings IA over unchanged legacy controls."""

from playwright.sync_api import expect


GROUPS = (
    "all",
    "career",
    "connection",
    "search",
    "templates",
    "ai",
    "advanced",
)


def _open_settings(ui):
    ui.open()
    page = ui.page
    expect(page.get_by_test_id("phase5-nav-settings")).to_be_visible()
    page.get_by_test_id("phase5-nav-settings").click()
    expect(page.locator("#panel-settings")).to_be_visible()
    expect(page.get_by_test_id("phase5-settings-toolbar")).to_be_visible()
    return page


def test_phase5_settings_toolbar_has_search_groups_and_save_semantics(ui):
    page = _open_settings(ui)

    expect(page.get_by_test_id("phase5-settings-search")).to_be_visible()
    for group in GROUPS:
        expect(page.get_by_test_id(f"phase5-settings-group-{group}")).to_be_visible()

    hint = page.get_by_test_id("phase5-settings-save-hint")
    expect(hint).to_contain_text("сохраняются сразу")
    expect(hint).to_contain_text("Сохранить")
    expect(hint).to_contain_text("Применить")


def test_phase5_settings_search_opens_matches_and_restores_open_state(ui):
    page = _open_settings(ui)
    proxy = page.locator("#proxy-section")
    llm = page.locator("#llm-section")

    page.evaluate("document.getElementById('proxy-section').open = false")
    assert page.evaluate("document.getElementById('proxy-section').open") is False

    search = page.get_by_test_id("phase5-settings-search")
    search.fill("прокси")

    expect(proxy).to_be_visible()
    expect(llm).to_be_hidden()
    assert page.evaluate("document.getElementById('proxy-section').open") is True

    page.get_by_test_id("phase5-settings-clear").click()
    expect(proxy).to_be_visible()
    expect(llm).to_be_visible()
    assert page.evaluate("document.getElementById('proxy-section').open") is False


def test_phase5_settings_group_filter_does_not_move_or_replace_controls(ui):
    page = _open_settings(ui)

    auto_send = page.locator("#llm-auto-send")
    original_parent = auto_send.evaluate("el => el.parentElement.tagName")

    page.get_by_test_id("phase5-settings-group-ai").click()
    expect(page.locator("#llm-section")).to_be_visible()
    expect(page.locator("#proxy-section")).to_be_hidden()
    expect(page.locator("#job-status-section")).to_be_hidden()
    assert auto_send.evaluate("el => el.parentElement.tagName") == original_parent

    page.get_by_test_id("phase5-settings-group-all").click()
    expect(page.locator("#proxy-section")).to_be_visible()
    expect(page.locator("#job-status-section")).to_be_visible()


def test_phase5_settings_advanced_group_collects_diagnostics_ws_and_json(ui):
    page = _open_settings(ui)
    page.get_by_test_id("phase5-settings-group-advanced").click()

    expect(page.locator("#ws-realtime-section")).to_be_visible()
    advanced = page.locator("#settings-panel > details.q-section[data-settings-group='advanced']")
    assert advanced.count() >= 3
    assert page.locator(
        "#settings-panel > details.q-section[data-settings-group='advanced'] > summary",
        has_text="JSON-редактор",
    ).count() == 1
    assert page.locator(
        "#settings-panel > details.q-section[data-settings-group='advanced'] > summary",
        has_text="Диагностика",
    ).count() == 1
    expect(page.locator("#llm-section")).to_be_hidden()
    expect(page.locator("#proxy-section")).to_be_hidden()


def test_phase5_settings_ctrl_k_focuses_search_without_changing_section(ui):
    page = _open_settings(ui)

    page.get_by_test_id("phase5-nav-settings").focus()
    page.keyboard.press("Control+K")
    expect(page.get_by_test_id("phase5-settings-search")).to_be_focused()
    expect(page.locator("#panel-settings")).to_be_visible()


def test_phase5_settings_mobile_filters_remain_reachable(ui):
    page = _open_settings(ui)
    page.set_viewport_size({"width": 390, "height": 844})

    advanced = page.get_by_test_id("phase5-settings-group-advanced")
    advanced.scroll_into_view_if_needed()
    expect(advanced).to_be_visible()
    advanced.click()
    expect(page.locator("#ws-realtime-section")).to_be_visible()
