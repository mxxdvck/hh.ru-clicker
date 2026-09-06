from app.manager import _select_quick_reply


def test_question_prefers_substantive_reply_over_greeting():
    replies = [
        "Здравствуйте!",
        "Да, могу подробнее рассказать об опыте и ответить на вопросы.",
    ]
    assert _select_quick_reply(replies, "Расскажите подробнее о вашем опыте?") == replies[1]


def test_question_rejects_short_greeting_only_reply():
    assert _select_quick_reply(["Здравствуйте!"], "Можем созвониться?") == ""


def test_non_question_keeps_normal_quick_reply_behavior():
    replies = ["Спасибо!", "Добрый день, спасибо за сообщение!"]
    assert _select_quick_reply(replies, "Приглашаем вас на следующий этап") == replies[1]