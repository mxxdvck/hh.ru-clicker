import copy

from playwright.sync_api import expect


def test_reused_account_index_rebuilds_card_and_selectors(ui):
    old = ui.state["accounts"][0]
    old.update({"idx": 0, "name": "Удаляемый", "short": "old",
                "resume_hash": "old-rh", "mode": "web"})
    ui.open()
    expect(ui.page.locator("#acc-name-0")).to_have_text("Удаляемый")

    replacement = copy.deepcopy(old)
    replacement.update({"name": "Новый аккаунт", "short": "new",
                        "resume_hash": "new-rh", "mode": "mobile"})
    ui.state["accounts"] = [replacement]
    ui.push_state()

    expect(ui.page.locator("#acc-name-0")).to_have_text("Новый аккаунт")
    expect(ui.page.locator("#job-status-account option")).to_have_count(1)
    expect(ui.page.locator("#job-status-account option")).to_have_text("Новый аккаунт")
    expect(ui.page.locator("#hedi-account option")).to_have_count(2)
    expect(ui.page.locator("#hedi-account option").nth(1)).to_have_text("Новый аккаунт")
    assert not ui.page_errors


def test_account_removal_clears_cards_and_feature_selectors(ui):
    ui.open()
    ui.state["accounts"] = []
    ui.push_state()

    expect(ui.page.locator("#accounts-grid .acc-card")).to_have_count(0)
    expect(ui.page.locator("#accounts-empty")).to_be_visible()
    expect(ui.page.locator("#job-status-account option")).to_have_count(1)
    expect(ui.page.locator("#job-status-account option")).to_have_text("Нет аккаунтов")
    expect(ui.page.locator("#hedi-account option")).to_have_count(1)
    assert not ui.page_errors


def test_mobile_verify_non_json_500_shows_real_error_without_pageerror(ui):
    ui.set_response("POST", r"/api/mobile-auth/verify$", status=500,
                    raw_body="Internal Server Error", content_type="text/plain")
    ui.open()
    ui.page.locator("#ma-code").evaluate("(el) => { el.value = '1234'; }")
    ui.page.evaluate("""async () => {
      const button = document.createElement('button');
      await mobileAuthVerify(button);
    }""")

    expect(ui.page.locator("#ma-status")).to_contain_text("не-JSON ответ (HTTP 500)")
    expect(ui.page.locator("#ma-status")).to_contain_text("Internal Server Error")
    assert not ui.page_errors


def test_open_json_editor_does_not_download_backup_on_every_ws_tick(ui):
    ui.open()
    ui.page.evaluate("""() => {
      const el = document.getElementById('json-all-details');
      el.open = true;
      el.dispatchEvent(new Event('toggle'));
    }""")
    ui.wait_until(lambda: any(c["path"] == "/api/backup" for c in ui.calls))
    # Chromium сам генерирует toggle при присвоении open; ручной dispatch выше
    # может дать второй стартовый load. Оба должны завершиться до baseline.
    ui.page.wait_for_timeout(500)
    initial = len([c for c in ui.calls if c["path"] == "/api/backup"])

    for _ in range(5):
        ui.push_state()
    ui.page.wait_for_timeout(1800)

    assert len([c for c in ui.calls if c["path"] == "/api/backup"]) == initial
    assert not ui.page_errors
