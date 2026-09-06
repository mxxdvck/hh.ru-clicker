import json
from pathlib import Path

import pytest

from app.llm_policy import evaluate_reply_decision


_CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "llm_policy_cases.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_phase4_reply_policy_corpus(case):
    decision = evaluate_reply_decision(
        {
            "answer": case["answer"],
            "action": case.get("action", "send"),
            "confidence": case.get("confidence", 0.95),
            "category": case.get("model_category", "general"),
            "evidence": case.get("evidence", []),
            "missing_facts": case.get("missing_facts", []),
            "reason": "corpus case",
        },
        employer_text=case["employer_text"],
        trusted_context=case.get("trusted_context", ""),
        min_confidence=0.88,
    )
    assert decision.category == case["expected_category"]
    assert decision.auto_send_allowed is case["expected_auto_send"]
    assert decision.action == ("send" if case["expected_auto_send"] else "review")
