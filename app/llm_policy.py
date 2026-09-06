"""Deterministic safety policy for LLM-assisted job-search communication.

The model may draft an answer, but this module decides whether that draft is
safe enough for unattended sending. Employer content is always untrusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re


_INJECTION_PATTERNS = (
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"forget\s+(all\s+)?previous\s+instructions?",
    r"reveal\s+(the\s+)?(system\s+)?prompt",
    r"system\s+prompt",
    r"developer\s+message",
    r"api[_\s-]?key",
    r"\u0441\u0435\u043a\u0440\u0435\u0442\u043d\w*\s+\u043f\u0440\u043e\u043c\u043f\u0442",
    r"\u0441\u0438\u0441\u0442\u0435\u043c\u043d\w*\s+\u043f\u0440\u043e\u043c\u043f\u0442",
    r"\u0438\u0433\u043d\u043e\u0440\u0438\u0440\w*\s+\u043f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\w*\s+\u0438\u043d\u0441\u0442\u0440\u0443\u043a\u0446",
    r"\u0437\u0430\u0431\u0443\u0434\w*\s+(\u0432\u0441\u0435\s+)?(\u043f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\w*\s+)?\u0438\u043d\u0441\u0442\u0440\u0443\u043a\u0446",
    r"\u0432\u044b\u0432\u0435\u0434\w*\s+(\u0441\u0438\u0441\u0442\u0435\u043c\u043d\w*|developer|system)\s+(prompt|\u043f\u0440\u043e\u043c\u043f\u0442|\u0438\u043d\u0441\u0442\u0440\u0443\u043a\u0446)",
    r"\u043f\u043e\u043a\u0430\u0436\u0438\w*\s+(api|\u043a\u043b\u044e\u0447|\u0442\u043e\u043a\u0435\u043d|prompt|\u043f\u0440\u043e\u043c\u043f\u0442)",
)


_SECRET_OUTPUT_PATTERNS = (
    r"\bsk-[A-Za-z0-9_-]{12,}\b",
    r"\bsk-ant-[A-Za-z0-9_-]{12,}\b",
    r"\bgsk_[A-Za-z0-9_-]{12,}\b",
    r"\bAIza[A-Za-z0-9_-]{20,}\b",
    r"\bhf_[A-Za-z0-9_-]{12,}\b",
    r"\bHH_BOT_[A-Z0-9_]+\b",
    r"\bOPENAI_API_KEY\b",
    r"\bAPI[_-]?KEY\s*[:=]",
    r"\b(?:access|auth|bearer)[_-]?token\s*[:=]",
)

_CATEGORY_MARKERS = {
    "salary": ("salary", "compensation", "pay range", "\u0437\u0430\u0440\u043f\u043b\u0430\u0442", "\u043e\u043a\u043b\u0430\u0434", "\u0434\u043e\u0445\u043e\u0434", "\u0432\u0438\u043b\u043a\u0430"),
    "relocation": ("relocat", "move to", "\u043f\u0435\u0440\u0435\u0435\u0437\u0434", "\u0440\u0435\u043b\u043e\u043a\u0430\u0446", "\u043a\u043e\u043c\u0430\u043d\u0434\u0438\u0440\u043e\u0432", "business trip"),
    "interview": ("interview", "phone call", "video call", "google meet", "zoom", "teams call", "\u0441\u043e\u0431\u0435\u0441\u0435\u0434", "\u0441\u043e\u0437\u0432\u043e\u043d", "\u0437\u0432\u043e\u043d\u043e\u043a", "\u0438\u043d\u0442\u0435\u0440\u0432\u044c\u044e", "\u0432\u0441\u0442\u0440\u0435\u0447\u0430 \u0441 \u0440\u0435\u043a\u0440\u0443\u0442"),
    "assignment": ("test task", "take-home", "coding challenge", "assessment", "home assignment", "\u0442\u0435\u0441\u0442\u043e\u0432", "\u0442\u0435\u0441\u0442\u043e\u0432\u043e\u0435 \u0437\u0430\u0434\u0430\u043d\u0438\u0435", "\u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u043e\u0435 \u0437\u0430\u0434\u0430\u043d\u0438\u0435 \u0434\u043b\u044f \u043e\u0442\u0431\u043e\u0440\u0430"),
    "commitment": ("nda", "non-disclosure", "confidentiality agreement", "sign the agreement", "\u043f\u043e\u0434\u043f\u0438\u0441\u0430\u0442\u044c nda", "\u0441\u043e\u0433\u043b\u0430\u0448\u0435\u043d\u0438\u0435 \u043e \u043d\u0435\u0440\u0430\u0437\u0433\u043b\u0430\u0448\u0435\u043d\u0438\u0438", "\u0442\u0440\u0443\u0434\u043e\u0432\u043e\u0439 \u0434\u043e\u0433\u043e\u0432\u043e\u0440", "\u043e\u0444\u0435\u0440"),
    "schedule": ("timezone", "time zone", "schedule", "office", "remote", "hybrid", "\u043c\u043e\u0441\u043a\u043e\u0432\u0441\u043a", "\u043c\u0441\u043a", "\u0447\u0430\u0441\u043e\u0432", "\u0433\u0440\u0430\u0444\u0438\u043a", "\u043e\u0444\u0438\u0441", "\u0443\u0434\u0430\u043b\u0435\u043d", "\u0433\u0438\u0431\u0440\u0438\u0434", "\u0441\u043c\u0435\u043d"),
    "availability": ("start date", "when can you start", "notice period", "\u0434\u0430\u0442\u0430 \u0432\u044b\u0445\u043e\u0434\u0430", "\u043a\u043e\u0433\u0434\u0430 \u0433\u043e\u0442\u043e\u0432\u044b \u0432\u044b\u0439\u0442\u0438", "\u043a\u043e\u0433\u0434\u0430 \u0441\u043c\u043e\u0436\u0435\u0442\u0435 \u043f\u0440\u0438\u0441\u0442\u0443\u043f\u0438\u0442\u044c", "\u043f\u0440\u0438\u0441\u0442\u0443\u043f\u0438\u0442\u044c"),
    "experience": ("experience", "years", "worked with", "\u043e\u043f\u044b\u0442", "\u0441\u0442\u0430\u0436", "\u0440\u0430\u0431\u043e\u0442\u0430\u043b", "\u0440\u0430\u0431\u043e\u0442\u0430\u043b\u0438", "erp", "1c", "1\u0441", "\u0442\u0435\u0445\u043d\u043e\u043b\u043e\u0433", "\u043d\u0430\u0432\u044b\u043a"),
    "personal": ("age", "how old", "years old", "married", "children", "citizenship", "nationality", "phone number", "email address", "telegram", "whatsapp", "passport", "work permit", "visa", "background check", "security check", "\u0438\u0441\u043f\u043e\u043b\u043d\u0438\u043b", "\u0441\u043a\u043e\u043b\u044c\u043a\u043e \u0432\u0430\u043c \u043b\u0435\u0442", "\u0432\u0430\u043c \u043b\u0435\u0442", "\u0432\u043e\u0437\u0440\u0430\u0441\u0442", "\u0441\u0435\u043c\u0435\u0439\u043d", "\u0434\u0435\u0442\u0438", "\u0433\u0440\u0430\u0436\u0434\u0430\u043d\u0441\u0442\u0432\u043e", "\u043d\u0430\u0446\u0438\u043e\u043d\u0430\u043b", "\u0442\u0435\u043b\u0435\u0444\u043e\u043d", "\u043f\u043e\u0447\u0442", "\u0442\u0435\u043b\u0435\u0433\u0440\u0430\u043c", "\u0432\u0430\u0442\u0441\u0430\u043f", "\u043f\u0430\u0441\u043f\u043e\u0440\u0442", "\u0441\u043d\u0438\u043b\u0441", "\u0438\u043d\u043d", "\u0434\u0430\u0442\u0430 \u0440\u043e\u0436\u0434\u0435\u043d\u0438\u044f", "\u0430\u0434\u0440\u0435\u0441", "\u0432\u0438\u0437\u0430", "\u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u0438\u0435 \u043d\u0430 \u0440\u0430\u0431\u043e\u0442\u0443", "\u043f\u043e\u043b\u0438\u0433\u0440\u0430\u0444"),
}

_PROFILE_FIELDS = (
    "salary_expectation",
    "timezone",
    "location",
    "relocation",
    "business_travel",
    "start_date",
    "work_format",
    "schedule",
)

_ALWAYS_REVIEW_CATEGORIES = {"personal", "interview", "assignment", "commitment"}
_HIGH_RISK_CATEGORIES = {"salary", "relocation", "schedule", "availability"}

_CATEGORY_EVIDENCE_PREFIXES = {
    "salary": ("salary_expectation:",),
    "availability": ("start_date:",),
}

_TRAVEL_MARKERS = ("travel", "business trip", "командиров")
_RELOCATION_MARKERS = ("relocat", "move to", "переезд", "релокац")
_TIMEZONE_MARKERS = ("timezone", "time zone", "мск", "часов")
_WORK_FORMAT_MARKERS = ("office", "remote", "hybrid", "офис", "удален", "гибрид")
_SCHEDULE_MARKERS = ("schedule", "shift", "график", "смен")


@dataclass
class ReplyDecision:
    answer: str = ""
    action: str = "review"
    category: str = "general"
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    reason: str = ""
    auto_send_allowed: bool = False


def prompt_injection_suspected(text: str) -> bool:
    value = str(text or "")[:12000]
    return any(re.search(pattern, value, flags=re.I) for pattern in _INJECTION_PATTERNS)


def classify_employer_text(text: str) -> str:
    value = str(text or "").casefold()
    if prompt_injection_suspected(value):
        return "prompt_injection"
    for category, markers in _CATEGORY_MARKERS.items():
        if any(marker in value for marker in markers):
            return category
    return "general"


def candidate_profile_text(profile: dict | None) -> str:
    profile = profile if isinstance(profile, dict) else {}
    lines = []
    for key in _PROFILE_FIELDS:
        value = str(profile.get(key) or "").strip()
        if value:
            lines.append(f"{key}: {value[:400]}")
    return "\n".join(lines)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def evidence_supported(evidence: str, trusted_context: str) -> bool:
    needle = _norm(evidence)
    haystack = _norm(trusted_context)
    if len(needle) < 4 or not haystack:
        return False
    return needle in haystack


def _evidence_prefixes_for(category: str, employer_text: str) -> tuple[str, ...]:
    text = _norm(employer_text)
    if category in _CATEGORY_EVIDENCE_PREFIXES:
        return _CATEGORY_EVIDENCE_PREFIXES[category]
    if category == "relocation":
        if any(marker in text for marker in _TRAVEL_MARKERS):
            return ("business_travel:",)
        return ("relocation:",)
    if category == "schedule":
        if any(marker in text for marker in _TIMEZONE_MARKERS):
            return ("timezone:",)
        if any(marker in text for marker in _WORK_FORMAT_MARKERS):
            return ("work_format:", "location:")
        if any(marker in text for marker in _SCHEDULE_MARKERS):
            return ("schedule:",)
        return ("schedule:", "timezone:", "work_format:", "location:")
    return ()


def _has_relevant_evidence(evidence: list[str], category: str, employer_text: str) -> bool:
    prefixes = _evidence_prefixes_for(category, employer_text)
    if not prefixes:
        return bool(evidence)
    return any(_norm(item).startswith(prefix) for item in evidence for prefix in prefixes)


def _relevant_profile_values(evidence: list[str], category: str, employer_text: str) -> list[tuple[str, str]]:
    prefixes = _evidence_prefixes_for(category, employer_text)
    out: list[tuple[str, str]] = []
    for item in evidence:
        normalized = _norm(item)
        for prefix in prefixes:
            if normalized.startswith(prefix):
                value = normalized[len(prefix):].strip()
                if value:
                    out.append((prefix[:-1], value))
                break
    return out


def _polarity(text: str) -> int:
    value = _norm(text)
    negative = (
        r"\b(?:no|not|cannot|can't|won't|\u043d\u0435\u0442)\b",
        r"\b\u043d\u0435\s+(?:\u0433\u043e\u0442\u043e\u0432\w*|\u043c\u043e\u0433\u0443|\u0441\u043e\u0433\u043b\u0430\u0441\w*|\u0440\u0430\u0441\u0441\u043c\u0430\u0442\u0440\u0438\u0432\u0430\w*)\b",
    )
    positive = (
        r"\b(?:yes|ready|can|\u0434\u0430|\u043c\u043e\u0433\u0443|\u0441\u043e\u0433\u043b\u0430\u0441\w*|\u0440\u0430\u0441\u0441\u043c\u0430\u0442\u0440\u0438\u0432\u0430\w*|\u0433\u043e\u0442\u043e\u0432\w*)\b",
    )
    if any(re.search(pattern, value, flags=re.I) for pattern in negative):
        return -1
    if any(re.search(pattern, value, flags=re.I) for pattern in positive):
        return 1
    return 0


def _semantic_tags(text: str) -> set[str]:
    value = _norm(text)
    tags = set()
    aliases = {
        "remote": ("remote", "\u0443\u0434\u0430\u043b\u0435\u043d", "\u0434\u0438\u0441\u0442\u0430\u043d\u0446"),
        "office": ("office", "\u043e\u0444\u0438\u0441"),
        "hybrid": ("hybrid", "\u0433\u0438\u0431\u0440\u0438\u0434"),
        "moscow_time": ("moscow", "\u043c\u043e\u0441\u043a", "\u043c\u0441\u043a"),
    }
    for tag, markers in aliases.items():
        if any(marker in value for marker in markers):
            tags.add(tag)
    return tags


_CLAIM_STOPWORDS = {
    "i", "my", "have", "has", "had", "with", "and", "the", "a", "an", "to", "of", "in",
    "work", "worked", "working", "experience", "yes", "no", "ready", "can",
    "\u044f", "\u043c\u043e\u0439", "\u043c\u043e\u044f", "\u043c\u043e\u0438", "\u0443", "\u043c\u0435\u043d\u044f", "\u0435\u0441\u0442\u044c", "\u0438\u043c\u0435\u044e", "\u0441", "\u0438", "\u0432", "\u043d\u0430", "\u043f\u043e", "\u043a", "\u0434\u043b\u044f",
    "\u0440\u0430\u0431\u043e\u0442\u0430\u043b", "\u0440\u0430\u0431\u043e\u0442\u0430\u043b\u0430", "\u0440\u0430\u0431\u043e\u0442\u0430\u044e", "\u043e\u043f\u044b\u0442", "\u0434\u0430", "\u043d\u0435\u0442", "\u0433\u043e\u0442\u043e\u0432", "\u0433\u043e\u0442\u043e\u0432\u0430", "\u043c\u043e\u0433\u0443",
}


def _claim_tokens(text: str) -> set[str]:
    tokens = set()
    for word in re.findall(r"[a-z\u0430-\u044f\u04510-9]+", _norm(text), flags=re.I):
        if word in _CLAIM_STOPWORDS:
            continue
        if len(word) < 3 and not any(ch.isdigit() for ch in word):
            continue
        tokens.add(word if len(word) <= 6 else word[:6])
    return tokens


def _factual_claim_grounded(answer: str, trusted_context: str) -> bool:
    claims = _claim_tokens(answer)
    if not claims:
        return True
    trusted = _claim_tokens(trusted_context)
    if not trusted:
        return False
    return len(claims & trusted) / len(claims) >= (2 / 3)


def _profile_value_consistent(answer: str, evidence: list[str], category: str, employer_text: str) -> bool:
    entries = _relevant_profile_values(evidence, category, employer_text)
    if not entries:
        return False
    answer_norm = _norm(answer)
    employer_norm = _norm(employer_text)
    answer_polarity = _polarity(answer_norm)
    any_match = False
    for key, value in entries:
        value_polarity = _polarity(value)
        if key in {"relocation", "business_travel"} and value_polarity:
            if answer_polarity and answer_polarity != value_polarity:
                return False
            if answer_polarity == value_polarity:
                any_match = True
                continue

        value_tags = _semantic_tags(value)
        answer_tags = _semantic_tags(answer_norm)
        employer_tags = _semantic_tags(employer_norm)
        if value_tags and answer_tags:
            if not (value_tags & answer_tags):
                return False
            any_match = True
            continue
        if value_tags and employer_tags and answer_polarity:
            question_matches = bool(value_tags & employer_tags)
            if (answer_polarity > 0) != question_matches:
                return False
            any_match = True
            continue

        value_numbers = re.findall(r"\d+", value)
        if value_numbers:
            answer_numbers = set(re.findall(r"\d+", answer_norm))
            employer_numbers = set(re.findall(r"\d+", employer_norm))
            if answer_numbers & set(value_numbers):
                any_match = True
                continue
            if answer_polarity > 0 and employer_numbers & set(value_numbers):
                any_match = True
                continue
            return False

        value_tokens = _claim_tokens(value)
        if value_tokens:
            answer_tokens = _claim_tokens(answer_norm)
            if value_tokens & answer_tokens:
                any_match = True
                continue
            employer_tokens = _claim_tokens(employer_norm)
            if answer_polarity > 0 and value_tokens & employer_tokens:
                any_match = True
                continue
    return any_match


def _numeric_claims_supported(answer: str, trusted_context: str) -> bool:
    claims = re.findall(r"(?<![\w])\d+(?:[ \u00a0.,]\d+)*(?![\w])", str(answer or ""))
    trusted_digits = re.sub(r"\D", "", str(trusted_context or ""))
    for claim in claims:
        digits = re.sub(r"\D", "", claim)
        if digits and digits not in trusted_digits:
            return False
    return True


def _general_answer_needs_evidence(answer: str) -> bool:
    value = _norm(answer)
    patterns = (
        r"\b(?:я\s+(?:работал|работала|работаю|жил|жила|живу|нахожусь|имею|получаю|получал|получала)|i\s+(?:work|worked|live|lived|have|earn|earned))\b",
        r"\b(?:мой|моя|мои|my)\s+(?:опыт|зарплат|город|локац|график|schedule|experience)",
        r"\b(?:у меня|i have)\b",
        r"(?<![\w])\d+(?:[ \u00a0.,]\d+)*(?![\w])",
    )
    return any(re.search(pattern, value, flags=re.I) for pattern in patterns)


def _safe_float(value) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0


def reply_decision_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "answer": {"type": "string"},
            "action": {"type": "string", "enum": ["send", "review", "skip"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "category": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "missing_facts": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        "required": ["answer", "action", "confidence", "category", "evidence", "missing_facts", "reason"],
    }


def evaluate_reply_decision(data: dict, *, employer_text: str, trusted_context: str,
                            min_confidence: float = 0.88) -> ReplyDecision:
    data = data if isinstance(data, dict) else {}
    answer = str(data.get("answer") or "").strip()[:1600]
    category = classify_employer_text(employer_text)
    model_category = str(data.get("category") or "").strip().lower()
    if category == "general" and model_category in set(_CATEGORY_MARKERS) | {"general"}:
        category = model_category
    action = str(data.get("action") or "review").strip().lower()
    if action not in {"send", "review", "skip"}:
        action = "review"
    confidence = _safe_float(data.get("confidence"))
    evidence = [str(v).strip()[:300] for v in (data.get("evidence") or []) if str(v).strip()][:8]
    missing = [str(v).strip()[:200] for v in (data.get("missing_facts") or []) if str(v).strip()][:8]
    reason = str(data.get("reason") or "").strip()[:500]

    decision = ReplyDecision(answer=answer, action=action, category=category, confidence=confidence,
                             evidence=evidence, missing_facts=missing, reason=reason)
    if not answer or action == "skip":
        return decision
    if category == "prompt_injection" or prompt_injection_suspected(employer_text):
        decision.action = "review"
        decision.reason = decision.reason or "prompt injection suspected"
        return decision
    if any(re.search(pattern, answer, flags=re.I) for pattern in _SECRET_OUTPUT_PATTERNS):
        decision.action = "review"
        decision.reason = "possible secret leakage in generated answer"
        return decision
    if missing or confidence < min_confidence or action != "send":
        decision.action = "review" if action != "skip" else "skip"
        return decision

    supported = [item for item in evidence if evidence_supported(item, trusted_context)]
    if category in _ALWAYS_REVIEW_CATEGORIES:
        decision.action = "review"
        decision.reason = decision.reason or f"{category} question requires explicit human review"
        return decision
    if category in _HIGH_RISK_CATEGORIES | {"experience"}:
        if not evidence or len(supported) != len(evidence):
            decision.action = "review"
            decision.reason = decision.reason or "high-risk factual answer lacks verifiable evidence"
            return decision
        if category != "experience" and not _has_relevant_evidence(evidence, category, employer_text):
            decision.action = "review"
            decision.reason = "evidence does not support the requested fact category"
            return decision
        if category != "experience" and not _profile_value_consistent(answer, evidence, category, employer_text):
            decision.action = "review"
            decision.reason = "generated answer is not consistent with the trusted profile value"
            return decision
        if not _numeric_claims_supported(answer, trusted_context):
            decision.action = "review"
            decision.reason = "generated answer contains an unsupported numeric claim"
            return decision
        if category == "experience" and not _factual_claim_grounded(answer, trusted_context):
            decision.action = "review"
            decision.reason = "experience claim is not sufficiently grounded in trusted facts"
            return decision
    elif evidence and len(supported) != len(evidence):
        decision.action = "review"
        decision.reason = decision.reason or "claimed evidence is not present in trusted context"
        return decision
    elif _general_answer_needs_evidence(answer):
        if not supported:
            decision.action = "review"
            decision.reason = "factual first-person claim lacks trusted evidence"
            return decision
        if not _factual_claim_grounded(answer, trusted_context):
            decision.action = "review"
            decision.reason = "factual first-person claim is not sufficiently grounded in trusted facts"
            return decision

    decision.auto_send_allowed = True
    return decision

@dataclass
class QuestionnaireFieldDecision:
    field: str
    values: list[str] = field(default_factory=list)
    category: str = "general"
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    reason: str = ""
    auto_fill_allowed: bool = False


@dataclass
class QuestionnaireBatch:
    answers: dict = field(default_factory=dict)
    review_fields: list[str] = field(default_factory=list)
    decisions: dict[str, QuestionnaireFieldDecision] = field(default_factory=dict)
    status: str = "review"
    reason: str = ""


def questionnaire_response_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "answers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "field": {"type": "string"},
                        "values": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "category": {"type": "string"},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                        "missing_facts": {"type": "array", "items": {"type": "string"}},
                        "reason": {"type": "string"},
                    },
                    "required": ["field", "values", "confidence", "category", "evidence", "missing_facts", "reason"],
                },
            },
        },
        "required": ["answers"],
    }


def evaluate_questionnaire_field(data: dict, *, question: dict, trusted_context: str,
                                 min_confidence: float = 0.88) -> QuestionnaireFieldDecision:
    data = data if isinstance(data, dict) else {}
    field_name = str(question.get("field") or "").strip()
    question_text = str(question.get("text") or "")
    qtype = str(question.get("type") or "textarea")
    options = question.get("options") or []
    allowed_values = {str(opt.get("value") or "") for opt in options if isinstance(opt, dict)}
    raw_values = data.get("values") or []
    if isinstance(raw_values, (str, int, float, bool)):
        raw_values = [raw_values]
    values = [str(v).strip()[:1200] for v in raw_values if str(v).strip()][:16]
    category = classify_employer_text(question_text)
    model_category = str(data.get("category") or "").strip().lower()
    if category == "general" and model_category in set(_CATEGORY_MARKERS) | {"general"}:
        category = model_category
    confidence = _safe_float(data.get("confidence"))
    evidence = [str(v).strip()[:300] for v in (data.get("evidence") or []) if str(v).strip()][:8]
    missing = [str(v).strip()[:200] for v in (data.get("missing_facts") or []) if str(v).strip()][:8]
    reason = str(data.get("reason") or "").strip()[:500]
    decision = QuestionnaireFieldDecision(
        field=field_name, values=values, category=category, confidence=confidence,
        evidence=evidence, missing_facts=missing, reason=reason,
    )

    if prompt_injection_suspected(question_text):
        decision.reason = reason or "prompt injection suspected in questionnaire"
        return decision
    if not values:
        decision.reason = reason or "questionnaire answer is empty"
        return decision
    if missing or confidence < min_confidence:
        decision.reason = reason or "questionnaire answer is uncertain or missing facts"
        return decision
    if qtype == "checkbox":
        if allowed_values and any(value not in allowed_values for value in values):
            decision.reason = "checkbox answer is not one of the form values"
            return decision
    else:
        if len(values) != 1:
            decision.reason = "single-value questionnaire field returned multiple values"
            return decision
        if allowed_values and values[0] not in allowed_values:
            decision.reason = "questionnaire answer is not one of the form values"
            return decision

    combined_answer = " ".join(values)
    if any(re.search(pattern, combined_answer, flags=re.I) for pattern in _SECRET_OUTPUT_PATTERNS):
        decision.reason = "possible secret leakage in questionnaire answer"
        return decision

    supported = [item for item in evidence if evidence_supported(item, trusted_context)]
    if category in _ALWAYS_REVIEW_CATEGORIES:
        decision.reason = reason or f"{category} questionnaire field requires explicit human review"
        return decision
    if category in _HIGH_RISK_CATEGORIES | {"experience"}:
        if not evidence or len(supported) != len(evidence):
            decision.reason = reason or "high-risk questionnaire answer lacks verifiable evidence"
            return decision
        if category != "experience" and not _has_relevant_evidence(evidence, category, question_text):
            decision.reason = reason or "questionnaire evidence does not support the requested fact category"
            return decision
        if category != "experience" and not _profile_value_consistent(combined_answer, evidence, category, question_text):
            decision.reason = "questionnaire answer is not consistent with the trusted profile value"
            return decision
        if not _numeric_claims_supported(combined_answer, trusted_context):
            decision.reason = reason or "questionnaire answer contains an unsupported numeric claim"
            return decision
        if category == "experience" and not _factual_claim_grounded(combined_answer, trusted_context):
            decision.reason = "questionnaire experience claim is not sufficiently grounded in trusted facts"
            return decision
    elif evidence and len(supported) != len(evidence):
        decision.reason = reason or "questionnaire evidence is not present in trusted context"
        return decision
    elif _general_answer_needs_evidence(combined_answer):
        if not supported:
            decision.reason = reason or "questionnaire factual claim lacks trusted evidence"
            return decision
        if not _factual_claim_grounded(combined_answer, trusted_context):
            decision.reason = "questionnaire factual claim is not sufficiently grounded in trusted facts"
            return decision

    decision.auto_fill_allowed = True
    return decision
