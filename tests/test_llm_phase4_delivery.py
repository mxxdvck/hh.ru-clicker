from pathlib import Path

from app.manager import _llm_delivery_mode, _questionnaire_event_summary, _robot_draft_metadata


def test_delivery_mode_requires_all_send_gates():
    assert _llm_delivery_mode(auto_send=True, auto_send_allowed=True, search_only=False) == "send"
    assert _llm_delivery_mode(auto_send=True, auto_send_allowed=False, search_only=False) == "review"
    assert _llm_delivery_mode(auto_send=False, auto_send_allowed=True, search_only=False) == "draft"
    assert _llm_delivery_mode(auto_send=True, auto_send_allowed=True, search_only=True) == "search_only"


def test_exception_backoff_is_guarded_by_actual_failure():
    source = (Path(__file__).parents[1] / "app/manager.py").read_text(encoding="utf-8")
    start = source.index("except Exception as e:\n                iteration_failed = True")
    end = source.index("state.llm_replied_count += replied", start)
    block = source[start:end]
    assert "if iteration_failed:" in block
    assert block.index("if iteration_failed:") < block.index("fail_count =")


def test_review_copy_does_not_claim_enabling_auto_send_will_send():
    source = (Path(__file__).parents[1] / "app/manager.py").read_text(encoding="utf-8")
    assert "вкл «Автоотправку» → отправлю" not in source
    assert "Auto safe не отправил" in source

def test_questionnaire_event_summary_uses_counts_not_answer_contents():
    info = {
        "questionnaire_fields": 3,
        "questionnaire_llm_fields": 2,
        "questionnaire_rule_fields": 1,
        "answer": "SECRET-VALUE",
    }
    summary = _questionnaire_event_summary(info)
    assert summary == "\u041e\u0442\u0432\u0435\u0442\u043e\u0432: 3 | LLM: 2 | \u043f\u0440\u0430\u0432\u0438\u043b\u0430: 1"
    assert "SECRET-VALUE" not in summary


def test_questionnaire_event_summary_handles_missing_or_bad_counts():
    assert _questionnaire_event_summary(None) == "\u041e\u043f\u0440\u043e\u0441 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d"
    assert _questionnaire_event_summary({"questionnaire_fields": "bad"}) == "\u041e\u043f\u0440\u043e\u0441 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d"

def test_robot_draft_metadata_distinguishes_review_manual_and_search_only():
    assert _robot_draft_metadata(auto_send=True, search_only=False, button_source="review") == (
        "robot_review", "robot button requires human review (review)",
    )
    assert _robot_draft_metadata(auto_send=False, search_only=False, button_source="safe_continue") == (
        "robot_draft_manual", "",
    )
    assert _robot_draft_metadata(auto_send=True, search_only=True, button_source="safe_continue") == (
        "robot_search_only", "",
    )
