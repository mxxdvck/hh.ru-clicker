"""
Questionnaire parsing and template-based answer generation.
"""

import re

from bs4 import BeautifulSoup

from app.config import CONFIG, questionnaire_default_answer
from app.logging_utils import log_debug


def _questionnaire_answer_with_source(question_text: str) -> tuple[str, bool]:
    """Return an answer and whether it came from an explicit user template."""
    q_lower = str(question_text or "").lower()
    for tmpl in CONFIG.questionnaire_templates:
        if not isinstance(tmpl, dict):
            continue
        keywords = tmpl.get("keywords", [])
        if not keywords:
            continue
        if any(str(kw).lower() in q_lower for kw in keywords if str(kw).strip()):
            answer = str(tmpl.get("answer") or "").strip()
            if answer:
                return answer, True
    return questionnaire_default_answer(), False


def get_questionnaire_answer(question_text: str) -> str:
    """Return a configured template answer, falling back only for free text."""
    answer, _matched = _questionnaire_answer_with_source(question_text)
    return answer


def _option_match_score(answer: str, option: dict) -> int:
    answer_norm = re.sub(r"\s+", " ", str(answer or "")).strip().casefold()
    if not answer_norm or not isinstance(option, dict):
        return 0
    answer_words = set(re.findall(r"\w+", answer_norm, flags=re.UNICODE))
    best = 0
    for raw in (option.get("label"), option.get("value")):
        candidate = re.sub(r"\s+", " ", str(raw or "")).strip().casefold()
        if not candidate:
            continue
        score = 0
        if answer_norm == candidate:
            score += 100
        elif len(candidate) >= 3 and candidate in answer_norm:
            score += 30
        elif len(answer_norm) >= 3 and answer_norm in candidate:
            score += 20
        candidate_words = set(re.findall(r"\w+", candidate, flags=re.UNICODE))
        score += 3 * len(answer_words & candidate_words)
        best = max(best, score)
    return best


def suggest_questionnaire_value(question: dict):
    """Conservative template suggestion. Selection fields never default to first."""
    qtype = str(question.get("type") or "textarea")
    answer, explicit_template = _questionnaire_answer_with_source(question.get("text", ""))
    if qtype == "textarea":
        return answer
    if not explicit_template:
        return [] if qtype == "checkbox" else ""
    options = [opt for opt in (question.get("options") or []) if isinstance(opt, dict)]
    scored = [(_option_match_score(answer, opt), opt) for opt in options]
    if qtype == "checkbox":
        return [str(opt.get("value") or "") for score, opt in scored if score > 0 and str(opt.get("value") or "")]
    if not scored:
        return ""
    best_score = max(score for score, _opt in scored)
    winners = [opt for score, opt in scored if score == best_score and score > 0]
    if len(winners) != 1:
        return ""
    return str(winners[0].get("value") or "")


def _parse_questionnaire_fields(html: str) -> tuple:
    """Return question texts and only conservatively resolved template answers."""
    rich_questions = _parse_questionnaire_rich(html)
    questions = [str(question.get("text") or "") for question in rich_questions]
    field_answers = {}
    for question in rich_questions:
        field_name = str(question.get("field") or "").strip()
        if not field_name:
            continue
        suggested = suggest_questionnaire_value(question)
        if question.get("type") == "checkbox":
            if suggested:
                field_answers[field_name] = list(suggested)
        elif str(suggested or "").strip():
            field_answers[field_name] = str(suggested)
    return questions, field_answers

def _parse_questionnaire_rich(html: str) -> list:
    """Parse questionnaire fields in DOM order, preserving question-to-field mapping."""
    soup = BeautifulSoup(html, "html.parser")
    task_name = re.compile(r"task_\d+")
    textarea_name = re.compile(r"task_\d+_text")

    def _label_for_input(inp, fallback: str) -> str:
        inp_id = inp.get("id")
        if inp_id:
            label = soup.find("label", attrs={"for": inp_id})
            if label:
                text = label.get_text(" ", strip=True)
                if text:
                    return text
        return fallback

    def _question_text(anchor) -> str:
        block = anchor.find_parent(attrs={"data-qa": "task-question"})
        if block is None:
            block = anchor.find_previous(attrs={"data-qa": "task-question"})
        return block.get_text(" ", strip=True) if block is not None else ""

    grouped: dict[str, dict] = {}
    ordered_names: list[str] = []
    for node in soup.find_all(["textarea", "input", "select"]):
        name = str(node.get("name") or "")
        qtype = ""
        if node.name == "textarea" and textarea_name.fullmatch(name):
            qtype = "textarea"
        elif node.name == "input" and task_name.fullmatch(name):
            input_type = str(node.get("type") or "").lower()
            if input_type in {"radio", "checkbox"}:
                qtype = input_type
        elif node.name == "select" and task_name.fullmatch(name):
            qtype = "select"
        if not qtype:
            continue

        if name not in grouped:
            grouped[name] = {"field": name, "type": qtype, "text": _question_text(node), "options": []}
            ordered_names.append(name)
        entry = grouped[name]
        if entry["type"] != qtype:
            continue
        if qtype in {"radio", "checkbox"}:
            value = str(node.get("value") or "")
            if value:
                entry["options"].append({"value": value, "label": _label_for_input(node, value)})
        elif qtype == "select":
            entry["options"] = [
                {"value": str(opt.get("value") or ""), "label": opt.get_text(" ", strip=True)}
                for opt in node.find_all("option")
            ]

    return [grouped[name] for name in ordered_names]
