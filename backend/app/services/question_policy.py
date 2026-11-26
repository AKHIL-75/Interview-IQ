"""Shared scope, complexity and duplicate safeguards for question generation."""
import logging
import re

from app.services.performance import span, timed

logger = logging.getLogger(__name__)
HR_TOPICS = ["Teamwork and disagreement", "Ownership and learning from mistakes",
             "Prioritizing competing deadlines", "Constructive feedback",
             "Motivation and career goals", "Communication and collaboration",
             "Project experience", "Adaptability", "Leadership", "Problem-solving",
             "Strengths and growth", "Handling pressure"]

# Asking which keyword to use or why a language is case-sensitive can test
# knowledge. Asking how to spell or pronounce an isolated word does not.
WORDING_QUESTION = re.compile(
    r"\b(?:spell(?:ing)?|spelled|pronounc\w*|correct (?:capitalization|punctuation|grammar)|"
    r"(?:fix|correct|repeat)\b[^?.]{0,50}\b(?:transcript|wording|typo))\b", re.IGNORECASE,
)
WORDING_FEEDBACK = re.compile(
    r"\b(?:transcri(?:pt\w*|bed)|speech recognition|phonetic|mispronunc\w*|pronunci\w*|"
    r"typo\w*|misspell\w*|spell(?:ed|ing)|punctuation|grammar|capitalization|"
    r"part of the response was unclear)\b|"
    r"\b(?:clarify|read|interpret|transcribe)\s+['\"][^'\"]+['\"]\s+as\s+['\"]", re.IGNORECASE,
)


def conceptual_feedback(improvements):
    return [item for item in improvements if not WORDING_FEEDBACK.search(item)]


def question_intent(text):
    """Classify the requested assessment, not its topic or model-supplied label.

    Positive behavioral action/object patterns allow technical context. A separate
    mechanics-task veto catches compound questions. Unrecognized intent stays
    unknown, so HR generation fails closed rather than trusting an HR label.
    """
    text = text.lower()
    # Evaluate independently requested clauses before allowing a behavioral cue.
    clauses = re.split(r"[?;]|\band\s+(?=(?:explain|define|compare|write|implement|describe how)\b)", text)
    if len([c for c in clauses if c.strip()]) > 1:
        intents = [question_intent(c) for c in clauses if c.strip()]
        if "Technical" in intents:
            return "Technical"
    technical_object = (r"(?:\w+\s+){0,5}(?:implementation|indexing|algorithm\w*|"
                        r"normalization|polymorphism|inheritance|encapsulation|"
                        r"hashmap|concurrenthashmap|tcp|udp|thread.safety|"
                        r"scheduling|complexity|architecture|data.structur\w*|multithread\w*)")
    mechanics = re.search(
        rf"\b(?:explain|define|compare|implement|debug|optimize|derive)\b[^?.;]{{0,65}}\b{technical_object}\b|"
        r"\b(?:write|implement)\b[^?.;]{0,35}\b(?:code|program|function|query)\b|"
        r"\b(?:how (?:does|do)|what (?:is|are))\b[^?.;]{0,45}\b(?:work|differ|difference|algorithm\w*|normalization|polymorphism|encapsulation)\b|"
        r"\b(?:explain|describe|walk\s+\w+\s+through)\s+(?:how (?!you (?:handled|resolved|communicated|prioritized|learned|managed|adapted|decided|responded|supported)\b)|the (?:internal|underlying))\b|"
        r"\b(?:design|implement|optimize|debug)\s+(?:a|an|the|your)\s+(?:\w+\s+){0,3}(?:system|cache|database|service|algorithm)\b",
        text)
    # Explaining a concept to people tests communication, not the concept itself.
    communication = re.search(r"\b(?:explain|communicat\w*)\b[^?.;]{0,100}\bto\s+(?:a\s+|an\s+|your\s+)?(?:non.technical|stakeholder|colleague|customer|teammate)", text)
    if mechanics and not communication:
        return "Technical"
    behavioral = re.search(
        r"\bteam\w*\b[^?.;]{0,40}\b(?:communication|collaboration|cohesion|morale)\b|"
        r"\b(?:disagreement\w*|conflict\w*|feedback|mistake\w*|setback\w*|deadline\w*|challenge\w*)\b[^?.;]{0,70}\byou\b[^?.;]{0,40}\b(?:resolv\w*|handl\w*|fac\w*|manag\w*|receiv\w*|made|overc\w*|respond\w*)\b|"
        r"\b(?:work\w*|collaborat\w*|cooperat\w*)\s+(?:closely\s+)?(?:with|in|on)\s+(?:a\s+|an\s+|your\s+)?(?:team\w*|colleague\w*|others|someone)\b|"
        r"\b(?:time|situation|occasion|example)\b[^?.;]{0,140}\b(?:you|your)\b[^?.;]{0,140}\b(?:disagreement\w*|conflict\w*|feedback|mistake\w*|setback\w*|deadline\w*)\b|"
        r"\b(?:collaborat\w*|worked)\s+with\s+(?:someone|a teammate|a colleague)\b[^?.;]{0,100}\b(?:disagreement\w*|conflict\w*|challenge\w*)\b|"
        r"\b(?:handle\w*|resolv\w*|manag\w*|navigat\w*|respond\w*|deal\w*)\b[^?.;]{0,100}\b(?:disagree\w*|conflict\w*|difficult\w*|feedback|criticism|pressure|stress|deadline\w*|mistake\w*|setback\w*|challenge\w*)\b|"
        r"\b(?:prioriti\w*|balanc\w*)\b[^?.;]{0,80}\b(?:deadline\w*|task\w*|responsibilit\w*|workload|demand\w*)\b|"
        r"\b(?:learn\w*|receiv\w*|accept\w*|incorporat\w*|giv\w*)\b[^?.;]{0,90}\b(?:mistake\w*|feedback|failure\w*|criticism|experience)\b|"
        r"\b(?:mistake\w*|failure\w*|setback\w*)\b[^?.;]{0,90}\blearn\w*\b|"
        r"\b(?:motivat\w*|strength\w*|weakness\w*|career goals|teamwork|leadership)\b|"
        r"\b(?:why|what)\b[^?.;]{0,70}\b(?:join|apply|attract\w*|interest\w*)\b[^?.;]{0,55}\b(?:company|role|position|organization|job)\b|"
        r"\b(?:collaborat\w*|communicat\w*|persuad\w*|delegat\w*|support\w*|listen\w*)\b[^?.;]{0,70}\b(?:team\w*|colleague\w*|stakeholder\w*|customer\w*|others|people)\b|"
        r"\b(?:your|you)\b[^?.;]{0,45}\b(?:contribution|ownership|responsibility|responsibilities)\b|"
        r"\b(?:adapt\w*|adjust\w*)\b[^?.;]{0,75}\b(?:change\w*|plans?|priorities|team\w*|expectations)\b|"
        r"\b(?:you|your)\b[^?.;]{0,70}\b(?:reach an? agreement|reach consensus|ke(?:ep|pt) .*? informed|take responsibility|take ownership)\b|"
        r"\b(?:decid\w*|choos\w*)\b[^?.;]{0,75}\b(?:best for (?:your|the) team|between competing priorities)\b|"
        r"\b(?:teammate|colleague|manager|stakeholder)\b[^?.;]{0,40}\bdisagree\w*\b|"
        r"\b(?:your|the) team\b[^?.;]{0,40}\b(?:faced a challenge|faced when|experienced a setback)\b|"
        r"\b(?:in that situation|in that example|in the same situation|in your example)\b[^?.;]{0,80}\b(?:you personally|would you|did you|change\w*|your action\w*|your decision)\b|"
        r"\bskill\b[^?.;]{0,45}\bimprov\w*\b", text)
    if communication or behavioral:
        return "HR"
    return None


def category_matches(text, category, allow_opening=False):
    if category not in ("Technical", "HR"):
        return False
    if is_opening(text):
        return allow_opening
    intent = question_intent(text)
    return intent == "HR" if category == "HR" else intent != "HR"


def saved_interview_type(session):
    """Resolve owned saved configuration only; never infer type from a question."""
    values = [session.get("interview_type"), (session.get("interview_config") or {}).get("interview_type"),
              (session.get("interview_plan") or {}).get("interview_type")]
    values = [v for v in values if v is not None]
    if not values or any(v not in ("Technical", "HR", "Mixed") for v in values) or len(set(values)) != 1:
        raise ValueError("Saved interview type is missing or inconsistent. Restore the session configuration before continuing.")
    return values[0]


def category_schedule(interview_type, count):
    if interview_type not in ("Technical", "HR", "Mixed"):
        raise ValueError("Invalid interview type")
    return ["HR" if i % 2 == 0 else "Technical" for i in range(count)] if interview_type == "Mixed" else [interview_type] * count

SUBJECT_TOPICS = {
    "Java": ["Java types and variables", "Java classes and objects", "Java collections", "Java exceptions", "Java interfaces", "Java concurrency"],
    "OOP": ["OOP classes and objects", "OOP encapsulation", "OOP inheritance", "OOP polymorphism", "OOP abstraction", "OOP composition"],
    "DSA": ["DSA arrays", "DSA linked lists", "DSA stacks and queues", "DSA searching", "DSA sorting", "DSA trees and graphs"],
    "DBMS and SQL": ["SQL tables and keys", "SQL joins", "DBMS normalization", "SQL aggregation", "DBMS transactions", "SQL indexes"],
    "Operating Systems": ["Operating Systems processes", "Operating Systems threads", "Operating Systems scheduling", "Operating Systems memory", "Operating Systems synchronization", "Operating Systems deadlocks"],
    "Computer Networks": ["Computer Networks layers", "Computer Networks TCP and UDP", "Computer Networks IP addressing", "Computer Networks DNS", "Computer Networks routing", "Computer Networks congestion"],
}
COMPLEXITY = {
    "Easy": "Test one foundational concept with a direct question. No architecture, concurrency scenarios or multi-step trade-offs.",
    "Medium": "Ask for explanation and application in one small concrete example or basic problem. Avoid advanced production architecture.",
    "Hard": "Ask for deeper reasoning about an edge case, constraints or a complex problem with justified trade-offs.",
}


def is_opening(text):
    return bool(re.search(r"introduce yourself|tell (?:me|us) about yourself|(?:your|educational|academic) background|your education|key technologies|brief introduction", text, re.I))


def subject_matches(text, subject):
    if not subject:
        return True
    # Require an explicit scope anchor, rather than trusting the model's topic label.
    anchors = {
        "Java": r"\bjava\b|\bjvm\b|\bjdk\b",
        "OOP": r"\boop\b|object.oriented|encapsulation|polymorphism|inheritance|abstraction|composition|\bclasses?\b|\bobjects?\b",
        "DSA": r"\bdsa\b|data structure|algorithm|array|linked list|stack|queue|\btrees?\b|\bgraphs?\b|sorting|searching|complexity",
        "DBMS and SQL": r"\bsql\b|\bdbms\b|database|\bquery\b|\bqueries\b|normalization|transaction|foreign key|primary key",
        "Operating Systems": r"operating system|\bos\b|process|thread|schedul|memory|deadlock|semaphore|mutex|kernel|paging",
        "Computer Networks": r"network|\btcp\b|\budp\b|\bip\b|\bdns\b|\bhttp\b|routing|packet|\bosi\b|congestion",
    }
    return bool(re.search(anchors[subject], text, re.I))


def _question_vectors(texts, vectors_by_text):
    with span("semantic.model_ready"):
        with span("semantic.module_import"):
            from app.services.semantic_matcher import get_embedding_model
        model = get_embedding_model()
    missing = list(dict.fromkeys(text for text in texts if text not in vectors_by_text))
    if missing:
        with span("semantic.encode"):
            vectors = model.encode(missing, convert_to_numpy=True, normalize_embeddings=True)
        vectors_by_text.update(zip(missing, vectors))
    return [vectors_by_text[text] for text in texts]


@timed("semantic.history_prepare")
def prepare_semantic_history(history, vectors_by_text):
    if history:
        try: _question_vectors(history, vectors_by_text)
        except Exception: logger.warning("Question semantic preparation unavailable")


@timed("semantic.duplicate_check")
def semantic_duplicate(text, history, vectors_by_text=None):
    """Reuse normalized history vectors; retain the existing 0.90 threshold."""
    if not history: return False
    try:
        vectors = _question_vectors([text, *history], {} if vectors_by_text is None else vectors_by_text)
        return any(float(vector @ vectors[0]) >= 0.90 for vector in vectors[1:])
    except Exception:
        logger.warning("Question semantic comparison unavailable; retaining lexical and opening guards")
        return False


def performance_level(evaluation):
    if evaluation is None or not {"score", "technicalAccuracy", "relevance"}.issubset(evaluation.model_fields_set):
        return "unknown"
    status = (evaluation.answer_status or "").upper()
    if status in ("ERROR", "UNAVAILABLE", "FAILED"):
        return "unknown"
    if status in ("INCORRECT", "NON_ANSWER", "IRRELEVANT") or evaluation.technicalAccuracy < 40 or evaluation.relevance <= 20:
        return "weak"
    if status == "PARTIAL":
        return "partial"
    if evaluation.technicalAccuracy >= 85 and evaluation.relevance >= 80:
        return "strong"
    return "partial"
