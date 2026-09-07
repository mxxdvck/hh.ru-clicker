"""Project Phase 5B: six-section shell over the unchanged legacy panels."""

from playwright.sync_api import expect


SECTIONS = (
    "overview",
    "vacancies",
    "applications",
    "communications",
    "resume",
    "settings",
)


def _wait_for_shell(page):
    expect(page.locator("#phase5-nav-shell")).to_be_visible()
    expect(page.locator("#phase5-primary-nav [data-section]")).to_have_count(6)


def _expect_active(locator):
    expect(locator).to_have_attribute("aria-current", "page")
    assert "active" in (locator.get_attribute("class") or "").split()


def test_phase5_shell_has_six_primary_destinations(ui):
    ui.open()
    page = ui.page
    _wait_for_shell(page)

    for section in SECTIONS:
        expect(page.get_by_test_id(f"phase5-nav-{section}")).to_be_visible()

    expect(page.locator("#tabs.phase5-legacy-tabs")).to_be_visible()
    assert page.locator("#tabs .tab[data-tab]").count() >= 11


def test_phase5_primary_navigation_reuses_legacy_panels(ui):
    ui.open()
    page = ui.page
    _wait_for_shell(page)

    page.get_by_test_id("phase5-nav-vacancies").click()
    expect(page.locator("#panel-db")).to_be_visible()
    _expect_active(page.get_by_test_id("phase5-nav-vacancies"))
    assert page.evaluate("location.hash") == "#vacancies/db"

    page.get_by_test_id("phase5-nav-communications").click()
    expect(page.locator("#panel-llm")).to_be_visible()
    _expect_active(page.get_by_test_id("phase5-nav-communications"))
    assert page.evaluate("location.hash") == "#communications/llm"


def test_phase5_legacy_tab_updates_primary_section_and_emits_event(ui):
    ui.open()
    page = ui.page
    _wait_for_shell(page)

    page.evaluate(
        """window.__phase5LastTabEvent = null;
        window.addEventListener('hh:tabchange', e => { window.__phase5LastTabEvent = e.detail; });"""
    )
    page.get_by_test_id("legacy-tab-hh").click()

    expect(page.locator("#panel-hh")).to_be_visible()
    _expect_active(page.get_by_test_id("phase5-nav-applications"))
    page.wait_for_function("window.__phase5LastTabEvent !== null")
    event = page.evaluate("window.__phase5LastTabEvent")
    assert event["section"] == "applications"
    assert event["tab"] == "hh"


def test_phase5_hash_deep_links_and_legacy_aliases(ui):
    ui.open()
    page = ui.page
    _wait_for_shell(page)

    page.evaluate("location.hash = '#communications/hedi'")
    expect(page.locator("#panel-hedi")).to_be_visible()
    _expect_active(page.get_by_test_id("phase5-nav-communications"))

    page.evaluate("location.hash = '#activity'")
    expect(page.locator("#panel-log")).to_be_visible()
    _expect_active(page.get_by_test_id("phase5-nav-overview"))


def test_phase5_shell_stays_horizontally_reachable_on_mobile(ui):
    ui.open()
    page = ui.page
    _wait_for_shell(page)
    page.set_viewport_size({"width": 390, "height": 844})

    nav = page.locator("#phase5-primary-nav")
    expect(nav).to_be_visible()
    last = page.get_by_test_id("phase5-nav-settings")
    last.scroll_into_view_if_needed()
    expect(last).to_be_visible()
    box = last.bounding_box()
    assert box is not None
    assert box["x"] < 390
    assert box["x"] + box["width"] > 0
