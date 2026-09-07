from playwright.sync_api import expect


PRIMARY_SECTIONS = (
    "overview",
    "vacancies",
    "applications",
    "communications",
    "resume",
    "settings",
)


def _boot(ui, width: int):
    ui.open()
    ui.page.set_viewport_size({"width": width, "height": 900})
    ui.push_state()
    expect(ui.page.get_by_test_id("phase5-nav-overview")).to_be_visible()
    return ui.page


def _assert_no_page_overflow(page, width: int):
    dims = page.evaluate(
        """() => ({
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth
        })"""
    )
    assert dims["client"] == width
    if dims["scroll"] > dims["client"] + 1:
        dims["offenders"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('body *'))
              .map(el => { const r = el.getBoundingClientRect(); return {tag: el.tagName, id: el.id, cls: el.className, left: r.left, right: r.right, width: r.width}; })
              .filter(x => x.right > document.documentElement.clientWidth + 1 || x.left < -1)
              .slice(0, 20)"""
        )
    assert dims["scroll"] <= dims["client"] + 1, dims


def test_phase5_mobile_polish_has_readable_text_and_touch_targets(ui):
    page = _boot(ui, 390)

    nav = page.get_by_test_id("phase5-nav-overview")
    nav_box = nav.bounding_box()
    assert nav_box is not None and nav_box["height"] >= 44

    kicker_px = page.locator(".phase5-location-kicker").evaluate(
        "el => parseFloat(getComputedStyle(el).fontSize)"
    )
    assert kicker_px >= 10

    page.get_by_test_id("phase5-nav-settings").click()
    search = page.locator(".phase5-settings-search")
    expect(search).to_be_visible()
    search_box = search.bounding_box()
    assert search_box is not None and search_box["height"] >= 40
    _assert_no_page_overflow(page, 390)


def test_phase5_primary_sections_do_not_create_page_overflow_at_768(ui):
    page = _boot(ui, 768)
    for section in PRIMARY_SECTIONS:
        page.get_by_test_id(f"phase5-nav-{section}").click()
        _assert_no_page_overflow(page, 768)


def test_phase5_primary_sections_fit_desktop_without_mobile_sizing(ui):
    page = _boot(ui, 1440)
    nav = page.get_by_test_id("phase5-nav-overview")
    nav_box = nav.bounding_box()
    assert nav_box is not None
    assert 48 <= nav_box["height"] <= 64

    for section in PRIMARY_SECTIONS:
        page.get_by_test_id(f"phase5-nav-{section}").click()
        _assert_no_page_overflow(page, 1440)
