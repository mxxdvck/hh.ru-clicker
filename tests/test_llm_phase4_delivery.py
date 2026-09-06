from pathlib import Path

from app.manager import _llm_delivery_mode


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
