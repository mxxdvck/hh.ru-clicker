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
    """Парсит форму опросника и возвращает богатую структуру для LLM:
    list of {field, type, text, options: [{value, label}]}
    """
    soup = BeautifulSoup(html, "html.parser")

    q_blocks = soup.find_all(attrs={"data-qa": "task-question"})
    q_texts = []
    for b in q_blocks:
        c = b.get_text(separator=' ', strip=True)
        q_texts.append(c)

    result = []
    q_idx = 0

    for textarea in soup.find_all("textarea", attrs={"name": re.compile(r"task_\d+_text")}):
        name = textarea.get("name")
        result.append({"field": name, "type": "textarea",
                       "text": q_texts[q_idx] if q_idx < len(q_texts) else "", "options": []})
        q_idx += 1

    radio_groups: dict = {}      # name -> [value, ...]
    radio_value_label: dict = {}  # (name, value) -> label_text
    radio_order: list = []
    for inp in soup.find_all("input", attrs={"type": "radio", "name": re.compile(r"task_\d+")}):
        n = inp.get("name")
        v = inp.get("value")
        if not (n and v):
            continue
        if n not in radio_groups:
            radio_groups[n] = []
            radio_order.append(n)
        radio_groups[n].append(v)
        inp_id = inp.get("id")
        if inp_id:
            label = soup.find("label", attrs={"for": inp_id})
            if label:
                lbl_text = label.get_text(strip=True)
                if lbl_text:
                    radio_value_label[(n, v)] = lbl_text

    default_labels = ["да", "нет"]
    for name in radio_order:
        vals = radio_groups[name]
        options = [
            {"value": v,
             "label": radio_value_label.get((name, v), default_labels[i] if i < len(default_labels) else v)}
            for i, v in enumerate(vals)
        ]
        result.append({"field": name, "type": "radio",
                       "text": q_texts[q_idx] if q_idx < len(q_texts) else "", "options": options})
        q_idx += 1

    checkbox_groups: dict = {}
    checkbox_order: list = []
    for inp in soup.find_all("input", attrs={"type": "checkbox", "name": re.compile(r"task_\d+")}):
        n = inp.get("name")
        v = inp.get("value")
        if not (n and v):
            continue
        if n not in checkbox_groups:
            checkbox_groups[n] = []
            checkbox_order.append(n)
        checkbox_groups[n].append(v)

    for name in checkbox_order:
        vals = checkbox_groups[name]
        options = [{"value": v, "label": v} for v in vals]
        result.append({"field": name, "type": "checkbox",
                       "text": q_texts[q_idx] if q_idx < len(q_texts) else "", "options": options})
        q_idx += 1

    # Select (dropdown) fields
    for sel in soup.find_all("select", attrs={"name": re.compile(r"task_\d+")}):
        sel_name = sel.get("name")
        options = []
        for opt in sel.find_all("option"):
            val = opt.get("value", "")
            label = opt.get_text(strip=True)
            options.append({"value": val, "label": label})
        q_text = q_texts[q_idx] if q_idx < len(q_texts) else ""
        q_idx += 1
        result.append({"field": sel_name, "type": "select", "text": q_text,
                       "options": options})

    return result
