"""
Answer Evaluation Engine Service — Evaluates candidate answers via local Qwen3.

Evaluation Pipeline:
    1. Pre-validation / Non-answer detection:
       - Empty or whitespace answer
       - Explicit non-answers ("I don't know", "no idea", "not sure", "yes", etc.)
       -> Immediate deterministic 0 score, answer_status="NON_ANSWER", a generated reference answer.
    2. Build structured prompt (enforcing answer_status, relevance gating, anti-hallucination).
    3. Invoke local Qwen3 via existing llm_service.
    4. Extract and validate dimension scores & answer_status:
       - "CORRECT" | "PARTIAL" | "INCORRECT" | "IRRELEVANT" | "NON_ANSWER"
    5. Apply Gating Rules:
       - Gate 1 (Non-answer): score = 0, tech = 0, rel = 0, dep = 0, cla = 0.
       - Gate 2 (Irrelevant): tech = 0, dep = 0, rel <= 10 -> score <= 5 (or 0).
       - Relevance Capping: rel <= 20 -> score capped at 10.
    6. Calculate deterministic overall score using weighted formula:
         Technical Accuracy: 60%
         Relevance:          30%
         Clarity:            10%
    7. Return validated AnswerEvaluationResponse.
"""
from app.services import llm_usage


import re
import time
import math
from typing import Any

from app.prompts.evaluation_prompts import build_evaluation_evidence_prompt, build_evaluation_prompt, detect_question_type
from app.core.config import settings
from app.schemas.evaluation import AnswerEvaluationRequest, AnswerEvaluationResponse, CONCEPTUAL_RUBRIC
from app.services import llm_service
from app.services.performance import metric, timed, span
from app.services.question_policy import WORDING_QUESTION, conceptual_feedback
from app.services.reference_answer import clean_feedback, conflicts_with_verified_project, reference_for, verified_reference


# Bound the model's response inside the existing generation budget. Put the
# evidence checks first so the model can base its classification on them.
_EVALUATION_OUTPUT = {
    "type": "object",
    "properties": {
        "interpretation": {"type": "string", "maxLength": 240},
        "evidence": {"type": "array", "maxItems": 2, "items": {"type": "string", "maxLength": 110}},
        "central_error": {"anyOf": [
            {"type": "null"},
            {"type": "object", "properties": {
                "claim": {"type": "string", "maxLength": 180},
                "reason": {"type": "string", "maxLength": 140},
                "impact": {"type": "string", "maxLength": 165},
            }, "required": ["claim", "reason", "impact"], "additionalProperties": False},
        ]},
        "answer_status": {"enum": ["CORRECT", "PARTIAL", "INCORRECT", "IRRELEVANT", "NON_ANSWER"]},
        **{key: {"type": "integer", "minimum": 0, "maximum": 100}
           for key in ("technicalAccuracy", "relevance", "clarity")},
        **{key: {"type": "array", "maxItems": 2, "items": {"type": "string", "maxLength": 225}}
           for key in ("strengths", "improvements", "missing_aspects")},
        "suggestedAnswer": {"type": "string", "maxLength": 430},
    },
    "required": ["interpretation", "evidence", "central_error", "answer_status", "technicalAccuracy", "relevance", "clarity"],
}
_EVIDENCE_REVIEW_OUTPUT = {
    "type": "object",
    "properties": {
        "verdict": {"enum": ["FUNDAMENTAL", "SECONDARY", "UNCLEAR", "MAIN_GAP", "TERMS_ONLY", "IRRELEVANT", "KEEP"]},
        "quote": {"type": "string", "maxLength": 180},
        "note": {"type": "string", "maxLength": 200},
        "central_impact": {"type": "string", "maxLength": 165},
        "accuracy": {"type": "integer", "minimum": 0, "maximum": 100},
        "relevance": {"type": "integer", "minimum": 0, "maximum": 100},
        "clarity": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": ["verdict", "quote", "note", "central_impact", "accuracy"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Pre-validation & Non-Answer Detection Patterns
# ---------------------------------------------------------------------------
NON_ANSWER_REGEX_LIST = [
    # "I don't know", "I dont know", "I don't know the answer", "don't know", etc.
    r"^(i\s+)?(do\s*n'?t|dont|do\s+not)\s+know(\s+the\s+answer)?(\s+(?:(?:to|about|of)\s+)?this(?:\s+(?:question|topic))?)?(?:\s+at all)?$",
    # "I have no idea", "no idea", "have no clue", "no clue", "have no knowledge"
    r"^(i\s+)?(have|got)?\s*no\s+(idea|clue|knowledge|concept|understanding|information|clues)(\s+(about|on|regarding|of)\s+this)?$",
    # "I'm not sure", "I am not sure", "not sure", "not really sure", "not too sure"
    r"^(i\s*'?m|i\s+am)?\s*(not|un)\s*(really\s+|too\s+)?(sure|aware|certain|familiar)(\s+(about|with|of)\s+this)?$",
    # "I can't answer this", "cannot answer", "unable to answer"
    r"^(i\s+)?(ca\s*n'?t|cannot|unable\s+to)\s+(answer|explain|tell|recall|remember)(\s+this(\s+question)?)?$",
    # "I don't remember", "cannot recall", "don't recall"
    r"^(i\s+)?(do\s*n'?t|dont|do\s+not|ca\s*n'?t|cannot)?\s*(remember|recall)(\s+this)?$",
    # "haven't learned", "have not learned", "haven't heard", "never heard"
    r"^(i\s+)?(have\s+n'?t|havent|have\s+not|never)\s+(learned|heard|studied|worked\s+with|seen)(\s+(about|of)?\s+this)?$",
    # "forgot", "i forgot"
    r"^(i\s+)?forgot(\s+this)?$",
    # "no comments", "no comment"
    r"^no\s+comments?$",
    # "not aware", "no knowledge"
    r"^(not\s+aware|no\s+knowledge)(\s+(about|of)\s+this)?$",
    # Single tokens or abbreviations
    r"^(idk|dunno|pass|skip|n/?a|none|nil|nothing|nope|yep|yeah|yes|no|ok|okay|sure|maybe|na)$",
]

COMPILED_NON_ANSWER_PATTERNS = [re.compile(p, re.IGNORECASE) for p in NON_ANSWER_REGEX_LIST]

# A review may label a stated gap as a false claim. Its rationale must
# describe an actual misconception before overriding a substantive answer.
_OMISSION_RATIONALE = re.compile(
    r"\b(?:candidate|answer|response)\s+(?:does not|doesn't|did not|didn't|fails to)\s+"
    r"(?:address|explain|mention|specify|describe|cover|provide|say)\b", re.IGNORECASE,
)
_NON_DOMINANT_RATIONALE = re.compile(
    r"\b(?:transcription|mispronunc\w*|pronunci\w*|phonetic|typo|misspell\w*|"
    r"punctuation|grammar|capitalization|ambiguous|could mean|likely meant|secondary|minor mistake|"
    r"(?:does not|doesn't) invalidate|otherwise correct|not central)\b", re.IGNORECASE,
)
_RELEVANCE_DISAGREEMENT = re.compile(
    r"\b(?:does not|doesn't|did not|fails to)\s+(?:address|answer)\b", re.IGNORECASE,
)
_CONTRADICTION_FEEDBACK = re.compile(
    r"\b(?:incorrect\w*|contradict\w*|correct (?:that|the claim)|inverts?|the opposite)\b|"
    r"\bcorrected from (?:the )?candidate(?:['’]s)? (?:claim|statement|assertion)\b|"
    r"\bclarify\b[^.!?]{0,160}\(\s*not\b", re.IGNORECASE,
)
_MECHANISM_QUESTION = re.compile(
    r"\b(?:how|why|explain|introduce yourself|walk me through|what is the (?:primary )?purpose)\b", re.I,
)
_LIST_QUESTION = re.compile(r"\b(?:list|enumerate|spell each|spell (?:the|these) words)\b", re.I)


def is_explicit_non_answer(candidate_answer: str) -> bool:
    """
    Detect explicit non-answers in a case-insensitive, punctuation-resilient manner.
    Handles polite prefixes ('sorry', 'honestly', 'apologies') and whitespace/punctuation variations.
    """
    clean = candidate_answer.strip()
    if not clean:
        return True

    # Strip surrounding quotation marks and punctuation
    norm = re.sub(r"^[\s\"'“”‘’.,!?;:()\[\]{}]+|[\s\"'“”‘’.,!?;:()\[\]{}]+$", "", clean).strip().lower()
    norm = norm.replace("’", "'")
    if not norm:
        return True

    # Strip conversational polite preambles
    stripped_preamble = re.sub(
        r"^(?:(?:sorry|i(?:'?m| am) sorry|apologies|honestly|to be honest|unfortunately|well|um+|uh+)\b[\s,]*)+",
        "",
        norm,
        flags=re.IGNORECASE,
    ).strip()
    stripped_preamble = re.sub(r"^[\s\"'“”‘’.,!?;:()\[\]{}]+|[\s\"'“”‘’.,!?;:()\[\]{}]+$", "", stripped_preamble).strip()

    for text_to_check in (norm, stripped_preamble):
        if not text_to_check:
            return True
        for pattern in COMPILED_NON_ANSWER_PATTERNS:
            if pattern.match(text_to_check):
                return True

    return False


def calculate_deterministic_score(
    technical_accuracy: int,
    relevance: int,
    depth: int,
    clarity: int,
    answer_status: str = "CORRECT",
    question_type: str = "TECHNICAL",
    *,
    terms_only: bool = False,
    dominant_error: bool = False,
) -> int:
    """Apply the rubric uniformly. Legacy depth and question_type arguments are ignored."""
    tech = max(0, min(100, int(technical_accuracy)))
    rel = max(0, min(100, int(relevance)))
    cla = max(0, min(100, int(clarity)))

    if answer_status in ("NON_ANSWER", "IRRELEVANT"):
        return 0

    rounded_score = round((60 * tech + 30 * rel + 10 * cla) / 100)

    if rel <= 20:
        return min(rounded_score, 10)

    # Surface relevance and phrasing must not rescue a failed central mechanism.
    if dominant_error and answer_status == "INCORRECT":
        return min(rounded_score, 19)
    if terms_only:
        return min(rounded_score, 39)

    return rounded_score



def _clamp_dimension(val: Any, default: int = 50) -> int:
    """Safely parse and clamp an integer score between 0 and 100."""
    try:
        if isinstance(val, (int, float)):
            return max(0, min(100, int(round(val))))
        if isinstance(val, str):
            clean = val.strip().rstrip("%")
            return max(0, min(100, int(round(float(clean)))))
    except Exception:
        pass
    return default


def _extract_dimension_scores(raw_data: dict[str, Any]) -> tuple[int, int, int, int]:
    """
    Extract technicalAccuracy, relevance, depth, clarity with resilient key mapping.
    """
    def dimension(*keys):
        value = next((raw_data[k] for k in keys if raw_data.get(k) is not None), None)
        try:
            numeric = float(value.strip().rstrip("%") if isinstance(value, str) else value)
        except (TypeError, ValueError):
            numeric = float("nan")
        if isinstance(value, bool) or not math.isfinite(numeric) or not 0 <= numeric <= 100:
            raise llm_service.LLMResponseParseError(f"Missing or invalid evaluation dimension: {keys[0]}")
        parsed = _clamp_dimension(value, default=-1)
        if parsed < 0 or isinstance(value, bool):
            raise llm_service.LLMResponseParseError(f"Missing or invalid evaluation dimension: {keys[0]}")
        return parsed

    return (
        dimension("technicalAccuracy", "technical_accuracy", "technical", "accuracy"),
        dimension("relevance", "relevancy"),
        _clamp_dimension(raw_data.get("depth", raw_data.get("completeness")), default=0),
        dimension("clarity", "communication"),
    )


def _extract_answer_status(raw_data: dict[str, Any], default: str = "CORRECT") -> str:
    """Extract and normalize answer_status from LLM output dictionary."""
    status_val = (
        raw_data.get("answer_status")
        or raw_data.get("answerStatus")
        or raw_data.get("status")
        or ""
    )
    if isinstance(status_val, str):
        clean = status_val.strip().upper()
        if clean in ("CORRECT", "PARTIAL", "INCORRECT", "IRRELEVANT", "NON_ANSWER"):
            return clean
        if "NON" in clean or "NOT_ANSWER" in clean or "NO_ANSWER" in clean:
            return "NON_ANSWER"
        if "IRRELEVANT" in clean or "OFF_TOPIC" in clean or "UNRELATED" in clean:
            return "IRRELEVANT"
        if "PARTIAL" in clean or "INCOMPLETE" in clean:
            return "PARTIAL"
        if "INCORRECT" in clean or "WRONG" in clean or "FALSE" in clean:
            return "INCORRECT"
        if "CORRECT" in clean or "ACCURATE" in clean:
            return "CORRECT"
    raise llm_service.LLMResponseParseError("Missing or invalid evaluation status.")


def _extract_string_list(raw_data: dict[str, Any], key: str, fallback_key: str | None = None) -> list[str]:
    """Extract and sanitize a list of strings from dictionary."""
    val = raw_data.get(key)
    if not val and fallback_key:
        val = raw_data.get(fallback_key)

    if isinstance(val, list):
        items = []
        for item in val:
            if isinstance(item, str):
                cleaned = item.strip()
                if cleaned:
                    items.append(cleaned)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("point") or str(item)
                if text.strip():
                    items.append(text.strip())
        return [cleaned for item in items if (cleaned := clean_feedback(item))]
    elif isinstance(val, str) and val.strip():
        return [cleaned] if (cleaned := clean_feedback(val)) else []
    return []


def _is_verbatim(quote: Any, source: str) -> bool:
    if not isinstance(quote, str):
        return False
    tokens = r"\w+|[+#><=~%&|*/^−-]"
    excerpt = re.findall(tokens, quote.casefold())
    words = re.findall(tokens, source.casefold())
    return bool(excerpt) and f" {' '.join(excerpt)} " in f" {' '.join(words)} "


def _listed_phrases(answer: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"[,;\n]", answer) if part.strip()]
    return parts if len(parts) >= 3 and all(len(part.split()) <= 4 for part in parts) else []


@timed("evaluation.evidence_review")
async def _review_evidence(request: AnswerEvaluationRequest, prior_claim: str, interpretation: str) -> dict[str, Any]:
    try:
        review = await llm_service.generate_json_response(
            prompt=build_evaluation_evidence_prompt(request, prior_claim, interpretation), think=False, num_predict=230, temperature=0,
            response_schema=_EVIDENCE_REVIEW_OUTPUT if settings.LLM_PROVIDER == "ollama" else None,
        )
    except llm_service.LLMResponseParseError:
        metric("evaluation.evidence_review_invalid")
        return {}
    return review if isinstance(review, dict) else {}


def _confirms_dominant_error(review, candidate_answer, question_type):
    claim = review.get("quote")
    note = review.get("note") or ""
    impact = review.get("central_impact") or ""
    return (review.get("verdict") == "FUNDAMENTAL" and question_type not in {"INTRODUCTION", "HR_BEHAVIORAL"}
            and isinstance(note, str) and isinstance(impact, str) and note.strip() and impact.strip()
            and (clean_feedback(note) or clean_feedback(impact)) and not _OMISSION_RATIONALE.search(note)
            and not _NON_DOMINANT_RATIONALE.search(f"{note} {impact}")
            and _is_verbatim(claim, candidate_answer) and len(re.findall(r"\w+", claim)) >= 3)


@timed("evaluation")
@llm_usage.operation("answer_evaluation")
async def evaluate_candidate_answer(
    request: AnswerEvaluationRequest | None = None,
    **kwargs: Any,
) -> AnswerEvaluationResponse:
    """
    Main orchestration function for Phase 10 Answer Evaluation Engine.

    Parameters
    ----------
    request : AnswerEvaluationRequest | None
        The question context, candidate answer, and configuration.
    **kwargs : Any
        Keyword arguments to build AnswerEvaluationRequest if request is not provided.

    Returns
    -------
    AnswerEvaluationResponse
        The structured evaluation result with question-type-aware gated deterministic score.
    """
    if request is None or not isinstance(request, AnswerEvaluationRequest):
        req_data = {}
        if isinstance(request, dict):
            req_data.update(request)
        req_data.update(kwargs)
        if "candidateAnswer" in req_data and "candidate_answer" not in req_data:
            req_data["candidate_answer"] = req_data.pop("candidateAnswer")
        if "expectedAnswer" in req_data and "expected_answer" not in req_data:
            req_data["expected_answer"] = req_data.pop("expectedAnswer")
        if "jobTitle" in req_data and "job_title" not in req_data:
            req_data["job_title"] = req_data.pop("jobTitle")
        if "relevantSkills" in req_data and "relevant_skills" not in req_data:
            req_data["relevant_skills"] = req_data.pop("relevantSkills")
        request = AnswerEvaluationRequest(**req_data)

    start_time = time.perf_counter()

    # Detect question evaluation type
    q_type = detect_question_type(
        question=request.question,
        stage=request.stage,
        category=request.category,
        topic=request.topic,
    )

    # 1. GATE 1 PRE-VALIDATION: Empty, whitespace, or explicit non-answers
    if is_explicit_non_answer(request.candidate_answer):
        reference = await reference_for(request)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000)
        return AnswerEvaluationResponse(
            score=0,
            rubric_version=CONCEPTUAL_RUBRIC,
            technicalAccuracy=0,
            clarity=0,
            depth=0,
            relevance=0,
            answer_status="NON_ANSWER",
            strengths=[],
            improvements=[
                "The response does not attempt to answer the question.",
                "Try stating one idea that addresses the question and explain it briefly.",
            ],
            missing_aspects=["response content"],
            suggestedAnswer=reference,
            question_type=q_type,
            processing_time_ms=elapsed_ms,
        )

    # 3. Build structured question-type aware evaluation prompt
    with span("evaluation.prompt"):
        prompt = build_evaluation_prompt(request)

    schema = _EVALUATION_OUTPUT if settings.LLM_PROVIDER == "ollama" else None
    if schema and verified_reference(request.question):
        # This reference is supplied by the application. Constrain only the
        # final output field and retain the grading prompt and evidence schema.
        schema = {**schema, "properties": {**schema["properties"], "suggestedAnswer": {"enum": [""]}}}

    # 4. Invoke Qwen3 via existing llm_service
    llm_output = await llm_service.generate_json_response(
        prompt=prompt,
        think=False,
        num_predict=600,
        temperature=0,
        response_schema=schema,
    )

    # 5. Extract dimension scores, answer_status, and missing_aspects
    if not isinstance(llm_output, dict):
        raise llm_service.LLMResponseParseError("Evaluation must be a JSON object.")
    with span("evaluation.parse_validate"):
        tech, rel, dep, cla = _extract_dimension_scores(llm_output)
        status = _extract_answer_status(llm_output)
        missing_aspects = _extract_string_list(llm_output, "missing_aspects")
        improvements = _extract_string_list(llm_output, "improvements", fallback_key="areas_to_improve")

    error = llm_output.get("central_error")
    claim = error.get("claim") if isinstance(error, dict) else None
    grounded_claim = _is_verbatim(claim, request.candidate_answer)
    evidence = llm_output.get("evidence")
    has_evidence = isinstance(evidence, list)
    non_answer_conflict = status == "NON_ANSWER" and has_evidence and any(
        _is_verbatim(item, request.candidate_answer) and len(item.split()) >= 4 for item in evidence
    )
    wording_is_requested = bool(WORDING_QUESTION.search(request.question))
    wording_check = (request.answer_source != "text" and not wording_is_requested
                     and len(conceptual_feedback(improvements)) < len(improvements))
    exact_word_check = wording_is_requested and status == "PARTIAL" and bool(evidence and missing_aspects)
    relevance_check = rel > 20 and any(_RELEVANCE_DISAGREEMENT.search(item) for item in improvements)
    contradiction_check = status == "PARTIAL" and any(_CONTRADICTION_FEEDBACK.search(item) for item in improvements)
    listed_phrases = _listed_phrases(request.candidate_answer)
    single_labels = sum(bool(re.fullmatch(r"[\w+#-]+[.!]?", part)) for part in listed_phrases)
    short_label_list = single_labels == len(listed_phrases) or (
        len(listed_phrases) >= 4 and single_labels == len(listed_phrases) - 1
        and all(re.fullmatch(r"[\w+#-]+(?:\s+[\w+#-]+)?[.!]?", part) for part in listed_phrases)
    )
    bare_labels = bool(listed_phrases and not _LIST_QUESTION.search(request.question)
                       and (wording_is_requested or _MECHANISM_QUESTION.search(request.question))
                       and short_label_list)
    terms_only = status in {"CORRECT", "PARTIAL"} and (bare_labels or (status == "PARTIAL" and evidence == []))
    dominant_error = False
    evidence_note = ""
    main_gap = None
    # A low provisional grade or a quoted phrase never authorizes a severe cap.
    # Reuse the existing bounded review only for substantive disagreements.
    if status == "INCORRECT" or grounded_claim or non_answer_conflict or (
        status in {"CORRECT", "PARTIAL"} and "central_error" in llm_output and has_evidence and not terms_only
        and (not evidence or any(not _is_verbatim(item, request.candidate_answer) for item in evidence)
             or wording_check or exact_word_check or relevance_check or contradiction_check or listed_phrases
             or (status == "CORRECT" and (missing_aspects or any(
                 not item.casefold().startswith("optional:") for item in improvements))))
    ):
        grounded_reading = (llm_output.get("interpretation") if wording_check and not grounded_claim and evidence
                            and all(_is_verbatim(item, request.candidate_answer) for item in evidence) else "")
        review = await _review_evidence(request, claim if grounded_claim else "",
                                        grounded_reading[:240] if isinstance(grounded_reading, str) else "")
        verdict, quote = review.get("verdict"), review.get("quote")
        note = clean_feedback(review.get("note"))
        review_confirms_irrelevance = verdict == "IRRELEVANT" or (
            verdict == "FUNDAMENTAL" and not review.get("central_impact")
            and _clamp_dimension(review.get("relevance"), default=100) <= 10
            and _is_verbatim(quote, request.candidate_answer)
        )
        if (status == "INCORRECT" or grounded_claim or contradiction_check or exact_word_check or non_answer_conflict
                ) and _confirms_dominant_error(review, request.candidate_answer, q_type):
            if non_answer_conflict:
                tech = _clamp_dimension(review.get("accuracy"), default=tech)
                rel = _clamp_dimension(review.get("relevance"), default=rel)
                cla = _clamp_dimension(review.get("clarity"), default=cla)
            status, tech, dominant_error = "INCORRECT", min(tech, 25), True
            evidence_note = note or clean_feedback(review.get("central_impact"))
        elif verdict == "MAIN_GAP" and note and (
            _is_verbatim(quote, request.question) or _is_verbatim(quote, request.candidate_answer)
        ):
            main_gap = note
            evidence_note = note
        elif verdict == "TERMS_ONLY":
            terms_only = True
            evidence_note = note
        elif review_confirms_irrelevance and (relevance_check or non_answer_conflict):
            status = "IRRELEVANT"
            improvements = []
        elif verdict in {"KEEP", "SECONDARY", "UNCLEAR"}:
            if status == "INCORRECT" or grounded_claim or wording_check or exact_word_check or non_answer_conflict:
                tech = _clamp_dimension(review.get("accuracy"), default=tech)
                rel = _clamp_dimension(review.get("relevance"), default=rel)
                cla = _clamp_dimension(review.get("clarity"), default=cla)
                status = "CORRECT" if verdict == "KEEP" and tech >= 85 else "PARTIAL"
                improvements = []
            if verdict == "SECONDARY" and note and (conceptual_feedback([note]) or wording_is_requested):
                evidence_note = note
            if verdict == "UNCLEAR":
                evidence_note = "Part of the response was unclear. Clarify the intended concept in your own words."
            if verdict == "KEEP" and status == "CORRECT":
                improvements = [item for item in improvements if item.casefold().startswith("optional:")]
    if status == "INCORRECT" and not dominant_error:
        status = "PARTIAL"
        improvements = []
    if terms_only:
        status = "PARTIAL"
        tech, rel = min(tech, 25), min(rel, 50)
        if bare_labels:
            evidence_note = "Explain how the relevant terms connect to the concept asked about."
    elif main_gap:
        status = "PARTIAL"
        tech = min(tech, 45)
        if not missing_aspects:
            missing_aspects = [main_gap]

    # Post-LLM Gate 1: If model flagged NON_ANSWER
    if status == "NON_ANSWER":
        tech = 0
        rel = 0
        dep = 0
        cla = 0

    # Post-LLM Gate 2: If model flagged IRRELEVANT or relevance is near-zero
    elif status == "IRRELEVANT" or rel <= 10:
        status = "IRRELEVANT"
        tech = 0  # Technical accuracy must not be awarded for answering a different question
        dep = 0
        rel = 0
        cla = 0

    if status == "CORRECT":
        missing_aspects = []

    # 7. Deterministic score calculation with shared weights and evidence safeguards.
    deterministic_score = calculate_deterministic_score(
        technical_accuracy=tech,
        relevance=rel,
        depth=dep,
        clarity=cla,
        answer_status=status,
        terms_only=terms_only,
        dominant_error=dominant_error,
    )

    # 8. Extract strengths, improvements, and suggested answer
    strengths = [item for item in _extract_string_list(llm_output, "strengths")
                 if not conflicts_with_verified_project(item, request.question)]
    if not wording_is_requested:
        improvements = conceptual_feedback(improvements)
    if evidence_note:
        improvements = [evidence_note]
    if dominant_error or terms_only:
        # The earlier draft may have praised a claim the review invalidated.
        strengths = []
    suggested = await reference_for(request,
        llm_output.get("suggestedAnswer") or llm_output.get("suggested_answer") or llm_output.get("reference_answer"))

    # Polish improvements and strengths based on status and question type
    if status == "NON_ANSWER":
        strengths = []
        if not improvements:
            improvements.append("The response does not attempt to answer the question.")
    elif status == "IRRELEVANT":
        strengths = []
        if not improvements:
            improvements.append("The response discusses an unrelated topic and does not address the question asked.")
    elif status == "CORRECT" and not strengths:
        strengths.append("Your answer correctly explains the core concept.")
    elif tech < 40 and q_type == "TECHNICAL" and not improvements:
        improvements.append("State the key concept and explain how it applies to the question.")

    elapsed_ms = round((time.perf_counter() - start_time) * 1000)

    return AnswerEvaluationResponse(
        score=deterministic_score,
        rubric_version=CONCEPTUAL_RUBRIC,
        technicalAccuracy=tech,
        clarity=cla,
        depth=dep,
        relevance=rel,
        answer_status=status,
        strengths=strengths,
        improvements=improvements,
        missing_aspects=missing_aspects,
        suggestedAnswer=suggested,
        question_type=q_type,
        processing_time_ms=elapsed_ms,
    )
