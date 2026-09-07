from types import SimpleNamespace

import pytest

import app.routes.data as data_routes
from app.llm_policy import ReplyDecision


def _row(**extra):
    row = {
        "neg_id": "n1", "acc": "Артем", "acc_color": "yellow",
        "employer": "Aston", "vacancy_title": "Аналитик 1С",
        "vacancy_id": "v1", "status": "draft", "llm_sent": False,
        "employer_last_msg": "Интересует ли вас наше предложение?",
    }
    row.update(extra)
    return row


def test_regenerate_builds_fresh_draft_without_sending(monkeypatch):
    row = _row()
    saved = {}
    state = SimpleNamespace(short="Артем", name="Артем", acc={"name": "Артем", "letter": ""}, cookies_expired=False)
    client = SimpleNamespace(
        fetch_chat_history=lambda *a, **k: [{"sender": "employer", "text": row["employer_last_msg"]}],
        fetch_resume=lambda: {"text": "1С разработчик"},
    )
    monkeypatch.setattr(data_routes, "_interview_row", lambda _id: {**row, **saved})
    monkeypatch.setattr(data_routes, "_state_for_interview", lambda _row: state)
    monkeypatch.setattr(data_routes, "get_client", lambda _acc: client)
    monkeypatch.setattr(data_routes.CONFIG, "chat_use_oauth", False)
    monkeypatch.setattr(data_routes.CONFIG, "llm_use_resume", True)
    monkeypatch.setattr(data_routes.CONFIG, "llm_use_cover_letter", False)
    monkeypatch.setattr(
        data_routes, "generate_llm_reply_decision",
        lambda *a, **k: ReplyDecision(
            answer="Добрый день! Да, предложение интересно. Готов обсудить подробнее.",
            action="send", category="interest", confidence=0.98, auto_send_allowed=True,
        ),
    )

    def fake_upsert(_neg_id, **kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(data_routes, "upsert_interview", fake_upsert)
    result = data_routes._regenerate_interview_sync("n1")

    assert result["llm_reply"].startswith("Добрый день! Да, предложение интересно")
    assert saved["llm_sent"] is False
    assert saved["llm_source"] == "llm_regenerated_review"
    assert saved["llm_category"] == "interest"


def test_regenerate_rejects_already_sent_reply(monkeypatch):
    monkeypatch.setattr(data_routes, "_interview_row", lambda _id: _row(status="replied", llm_sent=True))
    with pytest.raises(ValueError, match="уже отправлен"):
        data_routes._regenerate_interview_sync("n1")


def test_regenerate_reminder_rewrites_existing_draft_when_history_is_unavailable(monkeypatch):
    row = _row(
        employer="Бизнес и Технологии",
        employer_last_msg="Напоминаю про мой вопрос. Буду благодарен за ответ.",
        llm_reply="В моем опыте нет работы именно с конфигурацией 1С:УТ 8.3.",
        llm_category="experience",
    )
    saved = {}
    state = SimpleNamespace(short="Артем", name="Артем", acc={"name": "Артем"}, cookies_expired=False)
    client = SimpleNamespace(fetch_chat_history=lambda *a, **k: [])
    monkeypatch.setattr(data_routes, "_interview_row", lambda _id: {**row, **saved})
    monkeypatch.setattr(data_routes, "_state_for_interview", lambda _row: state)
    monkeypatch.setattr(data_routes, "get_client", lambda _acc: client)
    monkeypatch.setattr(data_routes, "fetch_negotiation_messages_oauth", lambda *a, **k: [])
    monkeypatch.setattr(data_routes, "rewrite_llm_draft", lambda *a, **k: "Именно с УТ 8.3 напрямую не работал.")
    monkeypatch.setattr(data_routes, "upsert_interview", lambda _id, **kwargs: saved.update(kwargs))

    result = data_routes._regenerate_interview_sync("n1")

    assert result["llm_reply"] == "Именно с УТ 8.3 напрямую не работал."
    assert saved["llm_sent"] is False
    assert saved["llm_source"] == "llm_regenerated_style_review"
    assert "История чата" in saved["llm_review_reason"]
