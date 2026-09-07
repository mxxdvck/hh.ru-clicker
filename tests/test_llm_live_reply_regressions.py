import app.llm as llm
import app.llm_policy as policy
from app.manager import _human_llm_reason, _llm_review_text, _select_quick_reply


def test_terminal_bot_notice_never_needs_reply():
    text = (
        "Спасибо! Ваши ответы отправлены работодателю. "
        "Если ваш отклик его заинтересует, он напишет в этом же чате."
    )
    assert policy.is_non_actionable_employer_message(text) is True
    decision = llm.generate_llm_reply_decision([
        {"sender": "employer", "text": text},
    ])
    assert decision.action == "skip"
    assert decision.category == "system"
    assert decision.answer == ""


def test_reminder_without_visible_question_requires_review_without_invention():
    text = "Здравствуйте, Артем! Напоминаю про мой вопрос. Если найдёте время для ответа, буду благодарен."
    decision = llm.generate_llm_reply_decision([
        {"sender": "employer", "text": text},
    ])
    assert decision.action == "review"
    assert decision.answer == ""
    assert "previous question" in decision.reason


def test_quick_reply_is_blocked_for_reminders_and_terminal_notices():
    replies = ["Могу работать в гибком графике"]
    assert _select_quick_reply(replies, "Напоминаю про мой вопрос") == ""
    assert _select_quick_reply(
        replies,
        "Спасибо! Ваши ответы отправлены работодателю.",
    ) == ""


def test_repeated_robot_question_reuses_prior_explicit_answer():
    buttons = [{"text": "Да"}, {"text": "Нет"}]
    conversation = [
        {"sender": "employer", "text": "Вас устраивает заработная плата, указанная в вакансии?"},
        {"sender": "applicant", "text": "да"},
        {"sender": "employer", "text": "Вы готовы работать по часовому поясу Мск стандартный рабочий день?"},
        {"sender": "applicant", "text": "да"},
        {"sender": "employer", "text": "Вас устраивает заработная плата, указанная в вакансии?"},
    ]
    idx, text, source = llm.pick_robot_button(buttons, conversation)
    assert (idx, text, source) == (0, "Да", "prior_answer")


def test_different_high_risk_robot_question_is_not_inferred_from_prior_yes():
    buttons = [{"text": "Да"}, {"text": "Нет"}]
    conversation = [
        {"sender": "employer", "text": "Вас устраивает заработная плата, указанная в вакансии?"},
        {"sender": "applicant", "text": "да"},
        {"sender": "employer", "text": "Готовы к релокации в Москву?"},
    ]
    assert llm.pick_robot_button(buttons, conversation) == (-1, "", "review")


def test_reminder_finds_latest_question_that_has_not_been_answered():
    conversation = [
        {"sender": "employer", "text": "Какой у вас опыт ERP?"},
        {"sender": "applicant", "text": "Работал с ERP."},
        {"sender": "employer", "text": "Когда сможете приступить?"},
        {"sender": "employer", "text": "Напоминаю про мой вопрос, буду благодарен за ответ."},
    ]
    assert policy.latest_unanswered_employer_question(conversation) == "Когда сможете приступить?"


def test_direct_question_with_waiting_phrase_is_not_misclassified_as_reminder():
    text = "Жду ответ: готовы приступить на следующей неделе?"
    assert policy.is_reminder_message(text) is False


def test_terminal_hr_wrapup_never_needs_reply():
    text = (
        "Артем, благодарю вас за время и ответы. Обязательно рассмотрим ваше резюме "
        "и результаты диалога в рамках процесса подбора и при положительном решении свяжемся с вами."
    )
    assert policy.is_non_actionable_employer_message(text) is True
    decision = llm.generate_llm_reply_decision([
        {"sender": "employer", "text": text},
    ])
    assert decision.action == "skip"
    assert decision.answer == ""


def test_review_without_answer_gets_human_copy_not_fake_draft():
    decision = policy.ReplyDecision(action="review", category="experience", missing_facts=["months with 1C:UT 8.3"])
    text = _llm_review_text(decision)
    assert "Нужно уточнить вручную" in text
    assert "1C:UT 8.3" in text
    assert "LLM не будет придумывать ответ" in text


def test_deepseek_empty_completion_retries_with_larger_budget(monkeypatch):
    calls = []
    profile = {"name": "DeepSeek", "api_key": "x", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash", "enabled": True}

    class Result:
        provider = "deepseek"
        model = "deepseek-v4-flash"
        latency_ms = 5
        attempts = 1
        request_id = ""

        def __init__(self, text):
            self.text = text

    def complete(*args, **kwargs):
        calls.append(kwargs["max_tokens"])
        if len(calls) == 1:
            return Result("")
        return Result('{"answer":"Здравствуйте!","action":"send","confidence":0.99,"category":"general","evidence":[],"missing_facts":[],"reason":""}')

    monkeypatch.setattr(llm, "_enabled_profiles", lambda _config: [profile])
    monkeypatch.setattr(llm, "_complete_chat", complete)
    monkeypatch.setattr(llm.CONFIG, "llm_profile_mode", "fallback")
    decision = llm.generate_llm_reply_decision([{"sender": "employer", "text": "Здравствуйте"}], account_key="empty-retry")
    assert calls == [1200, 2200]
    assert decision.answer == "Здравствуйте!"
    assert decision.auto_send_allowed is True


def test_provider_failure_reason_is_humanized_for_review_ui():
    assert _human_llm_reason("all configured providers failed") == "LLM-провайдер временно не смог сформировать ответ"
    decision = policy.ReplyDecision(action="review", reason="all configured providers failed")
    assert _llm_review_text(decision) == "Нужно проверить вручную: LLM-провайдер временно не смог сформировать ответ"


def test_empty_provider_status_keeps_concrete_failure(monkeypatch):
    profile = {"name": "DeepSeek", "api_key": "x", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash", "enabled": True}

    class Result:
        text = ""
        provider = "deepseek"
        model = "deepseek-v4-flash"
        latency_ms = 5
        attempts = 1
        request_id = ""

    monkeypatch.setattr(llm, "_enabled_profiles", lambda _config: [profile])
    monkeypatch.setattr(llm, "_complete_chat", lambda *args, **kwargs: Result())
    monkeypatch.setattr(llm.CONFIG, "llm_profile_mode", "fallback")
    decision = llm.generate_llm_reply_decision([{"sender": "employer", "text": "Здравствуйте"}], account_key="empty-status")
    status = llm.get_llm_last_status("empty-status", "reply")
    assert decision.action == "skip"
    assert status["provider"] == "deepseek"
    assert status["status"] == "empty_completion"
