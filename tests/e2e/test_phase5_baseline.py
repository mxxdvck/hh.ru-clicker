"""Project Phase 5A: UX compatibility/accessibility baseline before layout work."""

from playwright.sync_api import expect


LEGACY_TABS = (
    "main", "log", "applied", "tests", "db", "hh", "views",
    "apply", "llm", "hedi", "settings",
)

CRITICAL_TEST_IDS = (
    "global-pause",
    "apply-mode",
    "search-only-mode",
    "daily-apply-limit",
    "run-apply-limit",
    "use-oauth-apply",
    "auto-apply-tests",
    "llm-auto-send",
    "apply-account",
    "apply-vacancy",
)


def test_phase5_legacy_tabs_have_stable_a11y_contract_and_keyboard_activation(ui):
    ui.open()
    page = ui.page

    tabs = page.locator("#tabs")
    expect(tabs).to_have_attribute("role", "tablist")
    assert tabs.locator(".tab[data-tab]").count() >= len(LEGACY_TABS)

    for name in LEGACY_TABS:
        tab = page.get_by_test_id(f"legacy-tab-{name}")
        expect(tab).to_have_attribute("role", "tab")
        expect(tab).to_have_attribute("tabindex", "0")
        expect(tab).to_have_attribute("aria-controls", f"panel-{name}")

    target = page.get_by_test_id("legacy-tab-log")
    target.focus()
    target.press("Enter")
    expect(page.locator("#panel-log")).to_be_visible()
    expect(target).to_have_attribute("aria-selected", "true")
    expect(page.get_by_test_id("legacy-tab-main")).to_have_attribute("aria-selected", "false")

    target.press("ArrowRight")
    expect(page.locator("#panel-applied")).to_be_visible()
    expect(page.get_by_test_id("legacy-tab-applied")).to_be_focused()


def test_phase5_critical_actions_have_stable_test_ids(ui):
    ui.open()
    page = ui.page
    for test_id in CRITICAL_TEST_IDS:
        expect(page.get_by_test_id(test_id)).to_have_count(1)


def test_phase5_keyboard_focus_is_visible(ui):
    ui.open()
    page = ui.page

    found = False
    for _ in range(24):
        page.keyboard.press("Tab")
        test_id = page.evaluate(
            "document.activeElement && document.activeElement.getAttribute('data-testid')"
        )
        if isinstance(test_id, str) and test_id.startswith("legacy-tab-"):
            found = True
            break

    assert found, "primary navigation was not reachable through Tab navigation"
    focus_style = page.evaluate(
        """() => {
          const s = getComputedStyle(document.activeElement);
          return {style: s.outlineStyle, width: parseFloat(s.outlineWidth) || 0};
        }"""
    )
    assert focus_style["style"] != "none"
    assert focus_style["width"] >= 2


def test_phase5_reduced_motion_disables_decorative_scan(ui):
    ui.page.emulate_media(reduced_motion="reduce")
    ui.open()
    page = ui.page

    expect(page.locator("html")).to_have_class("phase5-a11y")
    animation = page.evaluate(
        "getComputedStyle(document.body, '::after').animationName"
    )
    assert animation == "none"


def test_phase5_mobile_390_keeps_primary_account_action_reachable(ui):
    # Boot at the normal test viewport because UIController.open() intentionally
    # waits for the connection dot to be visible. Then resize to exercise the
    # responsive layout itself; mobile CSS may hide that decorative dot.
    ui.open()
    ui.page.set_viewport_size({"width": 390, "height": 844})
    ui.push_state()
    page = ui.page

    card = page.locator("#card-0")
    expect(card).to_be_visible()
    cta = card.locator(".acc-actions button").first
    expect(cta).to_be_visible()
    box = cta.bounding_box()
    assert box is not None
    assert box["x"] < 390
    assert box["x"] + box["width"] > 0


def test_phase5_all_legacy_destinations_open_without_pageerror(ui):
    page_errors = []
    ui.page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    ui.open()

    for name in LEGACY_TABS:
        tab = ui.page.get_by_test_id(f"legacy-tab-{name}")
        tab.click()
        expect(ui.page.locator(f"#panel-{name}")).to_be_visible()

    assert page_errors == [], f"page errors while traversing legacy UI: {page_errors}"
