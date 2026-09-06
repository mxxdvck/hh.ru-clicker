import json
from pathlib import Path

import pytest

import app.llm as llm


_CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "llm_robot_policy_cases.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_phase4_robot_button_policy_corpus(monkeypatch, case):
    calls = []

    def fake_llm(*args, **kwargs):
        calls.append(True)
        return 0

    monkeypatch.setattr(llm, "_llm_pick_button_index", fake_llm)
    result = llm.pick_robot_button(
        [{"text": text} for text in case["buttons"]],
        [{"sender": "employer", "text": case["text"]}],
    )
    assert result == tuple(case["expected"])
    if case["llm_must_not_run"]:
        assert calls == []
    else:
        assert calls == [True]
