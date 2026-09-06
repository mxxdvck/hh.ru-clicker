import app.llm as llm


def _buttons(*texts):
    return [{"text": text} for text in texts]


def test_robot_safe_continue_can_choose_affirmative_without_llm(monkeypatch):
    monkeypatch.setattr(llm, "_llm_pick_button_index", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not run")))
    idx, text, source = llm.pick_robot_button(
        _buttons("Да", "Нет"),
        [{"sender": "employer", "text": "Вам интересна вакансия, готовы продолжить?"}],
    )
    assert (idx, text, source) == (0, "Да", "safe_continue")


def test_robot_relocation_question_never_asks_llm_to_guess(monkeypatch):
    called = []
    monkeypatch.setattr(llm, "_llm_pick_button_index", lambda *a, **k: called.append(True) or 0)
    result = llm.pick_robot_button(
        _buttons("Да", "Нет"),
        [{"sender": "employer", "text": "Готовы к релокации в Москву?"}],
    )
    assert result == (-1, "", "review")
    assert called == []
