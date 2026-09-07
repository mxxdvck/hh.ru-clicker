"""Project Phase 5G: persisted Review Center UX."""

from playwright.sync_api import expect


REVIEW_ROWS = [
    {
        "neg_id": "review-1", "acc": "ИВ", "employer": "Acme",
        "vacancy_title": "1C Developer", "status": "draft",
        "llm_source": "llm_review", "llm_category": "interview",
        "llm_review_reason": "Нельзя подтверждать время созвона без пользователя",
        "employer_last_msg": "Когда сможете созвониться?",
        "llm_reply": "Могу завтра после 15:00.", "last_seen": "2026-09-07T00:15:00",
    },
    {
        "neg_id": "review-2", "acc": "ИВ", "employer": "Beta",
        "vacancy_title": "1C ERP", "status": "draft",
        "llm_source": "robot_review", "llm_category": "robot",
        "llm_review_reason": "Robot action requires human review",
        "employer_last_msg": "Подтвердите NDA", "llm_reply": "Проверю условия вручную.",
    },
]


def _open_review(ui, rows=None):
    ui.data["interviews"] = list(REVIEW_ROWS if rows is None else rows)
    ui.open()
    ui.page.get_by_test_id("phase5-nav-communications").click()
    expect(ui.page.locator("#panel-llm")).to_be_visible()
    expect(ui.page.get_by_test_id("phase5-review-center")).to_be_visible()
    ui.page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=phase5-review-card]').length >= 0"
    )
    return ui.page


def test_phase5_review_center_shows_only_policy_review_drafts(ui):
    rows = list(REVIEW_ROWS) + [
        {"neg_id": "manual", "acc": "ИВ", "status": "draft",
         "llm_source": "llm_draft_manual", "llm_reply": "manual draft"},
        {"neg_id": "search", "acc": "ИВ", "status": "draft",
         "llm_source": "llm_search_only", "llm_reply": "search draft"},
        {"neg_id": "done", "acc": "ИВ", "status": "replied",
         "llm_source": "llm_review", "llm_review_reason": "old", "llm_reply": "sent"},
    ]
    page = _open_review(ui, rows)
    expect(page.get_by_test_id("phase5-review-count")).to_have_text("2 на проверку")
    expect(page.get_by_test_id("phase5-review-card")).to_have_count(2)
    expect(page.get_by_test_id("phase5-review-center")).to_contain_text("Нельзя подтверждать время созвона")
    expect(page.get_by_test_id("phase5-review-center")).not_to_contain_text("manual draft")


def test_phase5_review_center_filters_category_source_and_account(ui):
    rows = list(REVIEW_ROWS) + [{
        "neg_id": "review-3", "acc": "ДР", "employer": "Gamma", "status": "draft",
        "llm_source": "llm_review", "llm_category": "assignment",
        "llm_review_reason": "Тестовое задание требует проверки", "llm_reply": "Посмотрю задание.",
    }]
    page = _open_review(ui, rows)
    expect(page.get_by_test_id("phase5-review-count")).to_have_text("3 на проверку")

    page.get_by_test_id("phase5-review-account-filter").select_option("ДР")
    expect(page.get_by_test_id("phase5-review-count")).to_have_text("1 на проверку")
    expect(page.get_by_test_id("phase5-review-center")).to_contain_text("Тестовое задание")

    page.get_by_test_id("phase5-review-account-filter").select_option("")
    page.get_by_test_id("phase5-review-category-filter").select_option("robot")
    expect(page.get_by_test_id("phase5-review-count")).to_have_text("1 на проверку")
    expect(page.get_by_test_id("phase5-review-center")).to_contain_text("Beta")

    page.get_by_test_id("phase5-review-category-filter").select_option("")
    page.get_by_test_id("phase5-review-source-filter").select_option("llm_review")
    expect(page.get_by_test_id("phase5-review-count")).to_have_text("2 на проверку")


def test_phase5_review_center_only_exposes_safe_manual_actions(ui):
    ui.page.add_init_script(
        "Object.defineProperty(navigator, 'clipboard', {value:{writeText: async t => {window.__phase5Copied=t;}}, configurable:true});"
    )
    page = _open_review(ui)
    expect(page.get_by_test_id("phase5-review-count")).to_have_text("2 на проверку")

    first = page.get_by_test_id("phase5-review-card").first
    first.get_by_test_id("phase5-review-copy").click()
    page.wait_for_function("() => window.__phase5Copied === 'Могу завтра после 15:00.'")

    chat = first.get_by_test_id("phase5-review-open-chat")
    expect(chat).to_have_attribute("href", "https://hh.ru/chat/review-1")
    controls_text = page.get_by_test_id("phase5-review-center").inner_text().lower()
    assert "отправить" not in controls_text
    assert "send anyway" not in controls_text
    assert "approve" not in controls_text


def test_phase5_review_center_snapshot_does_not_spam_rest_and_refresh_does(ui):
    page = _open_review(ui)
    expect(page.get_by_test_id("phase5-review-count")).to_have_text("2 на проверку")

    def review_calls():
        return [c for c in ui.calls if c["method"] == "GET" and "status=draft" in c["url"]]

    assert len(review_calls()) == 1
    for _ in range(5):
        ui.push_state()
    page.wait_for_timeout(150)
    assert len(review_calls()) == 1

    page.get_by_test_id("phase5-review-refresh").click()
    ui.wait_until(lambda: len(review_calls()) == 2)


def test_phase5_review_center_surfaces_load_error_instead_of_false_empty(ui):
    ui.data["interviews"] = list(REVIEW_ROWS)
    ui.set_response("GET", r"/api/interviews$", body={"error": "boom"}, status=500)
    ui.open()
    ui.page.get_by_test_id("phase5-nav-communications").click()
    expect(ui.page.get_by_test_id("phase5-review-center")).to_contain_text("Не удалось загрузить review")


def test_phase5_review_center_mobile_actions_remain_reachable(ui):
    page = _open_review(ui)
    page.set_viewport_size({"width": 390, "height": 844})
    card = page.get_by_test_id("phase5-review-card").first
    card.scroll_into_view_if_needed()
    expect(card.get_by_test_id("phase5-review-copy")).to_be_visible()
    expect(card.get_by_test_id("phase5-review-open-chat")).to_be_visible()
    box = card.bounding_box()
    assert box is not None
    assert box["x"] >= 0
    assert box["x"] + box["width"] <= 390
