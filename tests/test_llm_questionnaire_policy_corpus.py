import json
from pathlib import Path

import pytest

from app.llm_policy import evaluate_questionnaire_field


_CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "llm_questionnaire_policy_cases.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_phase4_questionnaire_policy_corpus(case):
    decision = evaluate_questionnaire_field(
        {
            "field": case["question"]["field"],
            "values": case.get("values", []),
            "confidence": case.get("confidence", 0.95),
            "category": case.get("model_category", "general"),
            "evidence": case.get("evidence", []),
            "missing_facts": case.get("missing_facts", []),
            "reason": "corpus case",
        },
        question=case["question"],
        trusted_context=case.get("trusted_context", ""),
        min_confidence=0.88,
    )
    assert decision.category == case["expected_category"]
    assert decision.auto_fill_allowed is case["expected_auto_fill"]
