import re
from pathlib import Path


def test_auto_safe_checkbox_has_fail_closed_html_default():
    source = (Path(__file__).parents[1] / "static/index.html").read_text(encoding="utf-8")
    match = re.search(r'<input[^>]+id="llm-auto-send"[^>]*>', source)
    assert match is not None
    assert " checked" not in match.group(0)


def test_auto_safe_copy_promises_recheck_not_blind_send():
    source = (Path(__file__).parents[1] / "static/index.html").read_text(encoding="utf-8")
    assert "каждый ответ должен снова пройти policy gate" in source


def test_quick_setup_avoids_retired_provider_defaults():
    source = (Path(__file__).parents[1] / "static/js/app.js").read_text(encoding="utf-8")
    detect = source[source.index("function _llmDetectProvider"):source.index("async function llmQuickSetup")]
    assert "model:'deepseek-v4-flash'" in detect
    assert "model:'gemini-3.8-flash'" in detect
    assert "model:'openai/gpt-oss-120b'" in detect
    assert "model:'llama-3.3-70b-versatile'" not in detect


def test_review_drafts_stay_visible_when_auto_safe_is_on():
    source = (Path(__file__).parents[1] / "static/js/app.js").read_text(encoding="utf-8")
    assert "draftsBanner.style.display = visibleCount > 0 ? '' : 'none'" in source
    assert "function _llmDraftCounts" in source
    assert "String(l.source || '').includes('review')" in source
    assert "Math.max(fallbackReviews" in source
    assert "черновиков требуют ручной проверки" in source
    assert "требуют проверки" in source


def test_review_table_exposes_copy_and_hh_chat_actions():
    source = (Path(__file__).parents[1] / "static/js/app.js").read_text(encoding="utf-8")
    assert "function llmCopyDraft" in source
    assert "📋 Копировать" in source
    assert "Открыть чат HH" in source
    assert "llm_review_reason" in source
    assert "llm_category" in source
