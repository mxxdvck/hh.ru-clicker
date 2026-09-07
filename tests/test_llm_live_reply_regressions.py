import app.llm as llm
import app.llm_policy as policy
from app.config import CONFIG
from app.llm_provider import LLMResult
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


def test_interest_invitation_has_its_own_safe_category():
    assert policy.classify_employer_text("Интересует ли вас наше предложение?") == "interest"


def test_reply_prompt_forbids_assistant_like_long_interview(monkeypatch):
    captured = {}
    profile = {
        "name": "DeepSeek", "api_key": "x", "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash", "enabled": True,
    }
    monkeypatch.setattr(llm, "_enabled_profiles", lambda _config: [profile])
    monkeypatch.setattr(CONFIG, "llm_profile_mode", "fallback")
    monkeypatch.setattr(CONFIG, "llm_candidate_profile", {})

    def fake_complete(_profile, messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return LLMResult(
            text='{"answer":"Добрый день! Да, предложение интересно. Готов обсудить подробнее.",'
                 '"action":"send","confidence":0.99,"category":"interest","evidence":[],'
                 '"missing_facts":[],"reason":""}',
            provider="deepseek", profile="DeepSeek", model="deepseek-v4-flash",
            protocol="openai_compatible", latency_ms=10,
        )

    monkeypatch.setattr(llm, "_complete_chat", fake_complete)
    decision = llm.generate_llm_reply_decision([
        {"sender": "employer", "text": "Интересует ли вас наше предложение?"},
    ], account_key="style-interest")
    assert decision.category == "interest"
    assert decision.auto_send_allowed is True
    assert "Default to 1-3 short sentences" in captured["system"]
    assert "never like an assistant analysing a candidate" in captured["system"]


def test_interest_marker_does_not_hide_interview_risk():
    text = "Интересует ли вас вакансия? Когда сможете созвониться?"
    assert policy.classify_employer_text(text) == "interview"


def test_short_interest_ack_can_be_auto_sent_even_if_model_overreviews():
    decision = policy.evaluate_reply_decision(
        {
            "answer": "Добрый день! Да, предложение интересно. Готов обсудить подробнее.",
            "action": "review", "confidence": 0.60, "category": "interest",
            "evidence": [], "missing_facts": ["details"], "reason": "need details",
        },
        employer_text="Интересует ли вас наше предложение?",
        trusted_context="",
    )
    assert decision.category == "interest"
    assert decision.action == "send"
    assert decision.auto_send_allowed is True
    assert decision.missing_facts == []


def test_interest_template_ignores_decline_reason_examples():
    text = (
        "Добрый день! Интересует ли вас наше предложение?\n"
        "В случае отказа, не могли бы вы поделиться причиной (например: не мой стек, нашел работу, не подошел график)."
    )
    assert policy.classify_employer_text(text) == "interest"


def test_positive_interest_ack_overrides_contradictory_model_skip():
    decision = policy.evaluate_reply_decision(
        {
            "answer": "Добрый день! Да, предложение интересно.", "action": "skip",
            "confidence": 0.2, "category": "interest", "evidence": [],
            "missing_facts": [], "reason": "uncertain",
        },
        employer_text="Интересует ли вас наше предложение?", trusted_context="",
    )
    assert decision.action == "send"
    assert decision.auto_send_allowed is True


def test_interest_ack_does_not_bypass_work_format_safety():
    decision = policy.evaluate_reply_decision(
        {
            "answer": "Да, предложение интересно, но рассматриваю только удалённую работу.",
            "action": "send", "confidence": 0.99, "category": "interest",
            "evidence": [], "missing_facts": [], "reason": "",
        },
        employer_text="Интересует ли вас наше предложение?", trusted_context="",
    )
    assert decision.auto_send_allowed is False


def test_rewrite_llm_draft_keeps_manual_rewrite_short_and_fact_preserving(monkeypatch):
    profile = {
        "name": "DeepSeek", "api_key": "x", "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash", "enabled": True,
    }
    captured = {}
    monkeypatch.setattr(llm, "_enabled_profiles", lambda _config: [profile])

    def fake_complete(_profile, messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return LLMResult(
            text="Именно с УТ 8.3 напрямую не работал. Есть общий опыт разработки на 1С 8.3.",
            provider="deepseek", profile="DeepSeek", model="deepseek-v4-flash",
            protocol="openai_compatible", latency_ms=8,
        )

    monkeypatch.setattr(llm, "_complete_chat", fake_complete)
    result = llm.rewrite_llm_draft(
        "В моем опыте нет работы именно с конфигурацией 1С:УТ 8.3. Есть общий опыт разработки на 1С 8.3.",
        account_key="rewrite-test",
    )
    assert result.startswith("Именно с УТ 8.3")
    assert "Do not add dates, numbers, technologies" in captured["system"]
    assert "Preserve the factual meaning and uncertainty" in captured["system"]


def test_naturalize_review_draft_removes_resume_meta_language():
    source = (
        "В резюме нет опыта работы именно с конфигурацией 1С:УТ 8.3, "
        "поэтому точно ответить на этот вопрос не могу."
    )
    assert llm._naturalize_review_draft(source) == "Именно с 1С:УТ 8.3 напрямую не работал."


def test_rewrite_rejects_resume_meta_and_uses_deterministic_fallback(monkeypatch):
    profile = {"name": "DeepSeek", "api_key": "x", "enabled": True}
    monkeypatch.setattr(llm, "_enabled_profiles", lambda _config: [profile])
    monkeypatch.setattr(
        llm, "_complete_chat",
        lambda *a, **k: LLMResult(
            text="В резюме нет опыта работы именно с конфигурацией 1С:УТ 8.3.",
            provider="deepseek", profile="DeepSeek", model="deepseek-v4-flash",
            protocol="openai_compatible", latency_ms=5,
        ),
    )
    result = llm.rewrite_llm_draft(
        "В резюме нет опыта работы именно с конфигурацией 1С:УТ 8.3, поэтому точно ответить на этот вопрос не могу.",
        account_key="rewrite-meta-fallback",
    )
    assert result == "Именно с 1С:УТ 8.3 напрямую не работал."


def test_rewrite_naturalizes_model_bureaucratic_experience_answer(monkeypatch):
    profile = {"name": "DeepSeek", "api_key": "x", "enabled": True}
    monkeypatch.setattr(llm, "_enabled_profiles", lambda _config: [profile])
    monkeypatch.setattr(
        llm, "_complete_chat",
        lambda *a, **k: LLMResult(
            text="Опыта работы именно с конфигурацией 1С:УТ 8.3 нет, поэтому точно ответить на этот вопрос не могу.",
            provider="deepseek", profile="DeepSeek", model="deepseek-v4-flash",
            protocol="openai_compatible", latency_ms=5,
        ),
    )
    result = llm.rewrite_llm_draft(
        "В резюме нет опыта работы именно с конфигурацией 1С:УТ 8.3, поэтому точно ответить на этот вопрос не могу.",
        account_key="rewrite-naturalize-model",
    )
    assert result == "Именно с 1С:УТ 8.3 напрямую не работал."
