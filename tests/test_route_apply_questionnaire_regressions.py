"""Regressions for the dashboard's manual questionnaire flow."""

import asyncio
import types
from pathlib import Path

import app.routes.apply as apply_route
from app import apply_safety
from app.instances import bot


HTML = """
<div data-qa="task-question">Experience?</div>
<input type="radio" name="task_1" value="junior" id="r1">
<label for="r1">1-3 years</label>
<input type="radio" name="task_1" value="senior" id="r2">
<label for="r2">3-6 years</label>
<div data-qa="task-question">Frameworks?</div>
<input type="checkbox" name="task_2" value="django">
<input type="checkbox" name="task_2" value="fastapi">
<div data-qa="task-question">Format?</div>
<select name="task_3"><option value="remote">Remote</option><option value="office">Office</option></select>
"""


class Response:
    def __init__(self, status=200, text="", location=""):
        self.status = status
        self._text = text
        self.headers = {"location": location}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return self._text


class Session:
    def __init__(self, responses, captured, **kwargs):
        self.responses = responses
        self.captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, *args, **kwargs):
        return self.responses.pop(0)

    def post(self, *args, **kwargs):
        self.captured.extend(kwargs["data"].fields)
        return self.responses.pop(0)


class FormData:
    def __init__(self):
        self.fields = []

    def add_field(self, name, value):
        self.fields.append((name, value))


def fake_aiohttp(responses, captured=None):
    captured = captured if captured is not None else []
    return types.SimpleNamespace(
        ClientSession=lambda **kwargs: Session(responses, captured, **kwargs),
        ClientTimeout=lambda **kwargs: kwargs,
        FormData=FormData,
    )


def test_manual_parser_keeps_radio_labels_checkbox_and_select(monkeypatch):
    monkeypatch.setattr(apply_route, "aiohttp", fake_aiohttp([Response(text=HTML)]))
    acc = {"cookies": {}, "resume_hash": "rh"}

    result = asyncio.run(apply_route._fetch_questionnaire_data(acc, "123"))

    radio, checkbox, select = result["questions"]
    assert [item["label"] for item in radio["options"]] == ["1-3 years", "3-6 years"]
    assert radio["suggested"] == ""
    assert checkbox["suggested"] == []
    assert select["suggested"] == ""
    assert select["options"][1] == {"value": "office", "label": "Office"}


def test_submit_encodes_checkbox_as_repeated_fields(monkeypatch):
    captured = []
    responses = [Response(text="<input type=hidden name=x value=y>"),
                 Response(status=302, location="/applicant/negotiations")]
    monkeypatch.setattr(apply_route, "aiohttp", fake_aiohttp(responses, captured))
    acc = {"name": "A", "cookies": {"_xsrf": "x"}, "resume_hash": "rh",
           "letter": "", "mode": "web"}
    monkeypatch.setattr(bot, "_get_apply_acc", lambda idx: dict(acc))
    monkeypatch.setattr(bot, "_get_apply_state", lambda idx: None)
    monkeypatch.setattr(bot, "_add_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(apply_safety.storage, "add_applied", lambda *args, **kwargs: None)
    monkeypatch.setattr(apply_route, "get_client", lambda account: object())

    result = asyncio.run(apply_route.api_apply_submit({
        "account_idx": 0,
        "vacancy_id": "123",
        "answers": {"task_2": ["django", "fastapi"]},
    }))

    assert result["status"] == "sent"
    assert captured.count(("task_2", "django")) == 1
    assert captured.count(("task_2", "fastapi")) == 1
    assert not any(name == "task_2" and value.startswith("[") for name, value in captured)


def test_apply_result_messages_are_rendered_as_text():
    source = (Path(__file__).parents[1] / "static/js/app.js").read_text(encoding="utf-8")
    function = source[source.index("function applyShowResult"):source.index("function applyHideQuestionnaire")]
    assert "el.textContent = msg" in function
    assert "el.innerHTML = msg" not in function
