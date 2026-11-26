"""
Adaptive Interview Decision Engine & Dynamic Question Generator.

Consumes Phase 10 evaluation results to deterministically decide the next interview action:
- TARGETED_FOLLOW_UP: For weak, incomplete, shallow, or unclear answers (uses candidate response)
- DEEPER_CHALLENGE: For strong answers to probe deeper on the same topic (concurrency, trade-offs)
- NEXT_TOPIC: When answer is satisfactory or consecutive follow-up limit is reached
- ADVANCE_DIFFICULTY: When candidate demonstrates sustained strong performance across history
- RECOVERY_QUESTION: For non-answers ("I don't know"), steps back to basics without harsh drilling
- END_INTERVIEW: Concludes dynamic or static sessions when stopping criteria or question caps are met

Separates INTERVIEW PLANNING (WHAT to assess) from QUESTION GENERATION (HOW to phrase it naturally via Qwen3).
"""
from app.services import llm_usage


import asyncio
import copy
import difflib
from itertools import chain
import logging
import re
import random
import time
from typing import Any

from app.core.config import settings
from app.services.performance import timed, metric
from app.prompts.adaptive_prompts import (
    build_adaptive_followup_prompt,
    build_adaptive_retry_prompt,
    build_single_question_prompt,
)
from app.schemas.adaptive import (
    AdaptiveDecisionResult,
    AdaptiveDecisionType,
    AdaptiveEvaluationInput,
    AdaptiveLLMQuestionOutput,
    AdaptiveNextQuestionRequest,
    AdaptiveNextQuestionResponse,
    InterviewStartRequest,
    InterviewStartResponse,
)
from app.schemas.interview import GeneratedQuestion, InterviewDifficulty, InterviewStage
from app.services.project_context import named_projects, resolve_project, explicit_project_question, refers_to_project, FOLLOW_UPS
from app.schemas.job import JobProfile
from app.schemas.resume import CandidateProfile
from app.services import llm_service
from app.services.evaluator import is_explicit_non_answer
from app.services.hr_questions import grounded_hr_follow_up, hr_fallback_candidates
from app.services.llm_service import (
    LLMResponseParseError,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
)

from app.services.question_policy import (SUBJECT_TOPICS, HR_TOPICS, is_opening, subject_matches,
    semantic_duplicate, prepare_semantic_history, performance_level, category_matches, category_schedule, question_intent,
    conceptual_feedback, WORDING_QUESTION)

logger = logging.getLogger(__name__)

class InterviewStateError(ValueError):
    """Saved session configuration cannot support progression."""


MAX_CONSECUTIVE_FOLLOWUPS = 2
MAX_GENERATION_RETRIES = 3
MIN_DYNAMIC_QUESTIONS = 5
MAX_DYNAMIC_QUESTIONS = 20

DIFFICULTY_LEVELS: list[InterviewDifficulty] = ["Easy", "Medium", "Hard"]


def _clean_text_for_comparison(text: str) -> str:
    """Normalize text by stripping non-alphanumeric characters and lowercase."""
    return re.sub(r"[^\w\s]", "", text).lower().strip()


def is_duplicate_question(new_q: str, history: list[str], threshold: float = 0.80, allow_opening: bool = False) -> bool:
    """
    Determines whether new_q is a duplicate or near-duplicate of any question in history.
    Uses normalized string equality and token/sequence similarity.
    """
    clean_new = _clean_text_for_comparison(new_q)
    if not clean_new:
        return True

    if not allow_opening and is_opening(new_q) and any(is_opening(q) for q in history):
        return True
    words_new = set(clean_new.split())

    for existing in history:
        clean_exist = _clean_text_for_comparison(existing)
        if not clean_exist:
            continue

        # 1. Exact normalized match
        if clean_new == clean_exist:
            return True

        # 2. Sequence matcher ratio
        ratio = difflib.SequenceMatcher(None, clean_new, clean_exist).ratio()
        if ratio >= threshold:
            return True

        # 3. Jaccard word set overlap for longer questions
        words_exist = set(clean_exist.split())
        if words_new and words_exist:
            intersection = len(words_new.intersection(words_exist))
            union = len(words_new.union(words_exist))
            if union > 0 and (intersection / union) >= threshold:
                return True

    return False


def _extract_target_concept(evaluation: AdaptiveEvaluationInput, current_topic: str) -> str:
    """Extract a concise target concept from evaluation improvements or topic."""
    improvements = conceptual_feedback(evaluation.improvements)
    if improvements:
        first_imp = improvements[0].strip()
        clean = re.sub(r"^(the answer|candidate|should|could|must|incorrectly|lacks|missing)\s+", "", first_imp, flags=re.IGNORECASE)
        if len(clean) > 80:
            clean = clean[:77] + "..."
        return clean
    return f"{current_topic} core mechanics"


def should_end_dynamic_session(
    interview_state_or_count: dict[str, Any] | int,
    min_questions: int = 5,
    max_questions: int = 20,
    covered_stages: list[str] | None = None,
    covered_topics: list[str] | None = None,
    recent_scores: list[int] | None = None,
    consecutive_weak_answers: int = 0,
    consecutive_strong_answers: int = 0,
) -> tuple[bool, str]:
    """
    Evaluates whether a dynamic interview has collected sufficient signal to conclude safely.
    Strictly enforces min_questions (>= 5) and max_questions (<= 20).
    Never terminates prematurely after a single bad answer.
    """
    if isinstance(interview_state_or_count, dict):
        st = interview_state_or_count
        q_asked = st.get("questions_asked", 0)
        min_q = st.get("min_questions", min_questions)
        max_q = st.get("max_questions", max_questions)
        c_stages = covered_stages or st.get("covered_stages") or st.get("topics_covered") or []
        c_topics = covered_topics or st.get("covered_topics") or st.get("topics_covered") or []
        r_scores = recent_scores or st.get("recent_scores") or []
        w_answers = consecutive_weak_answers or st.get("consecutive_weak_answers", 0)
        s_answers = consecutive_strong_answers or st.get("consecutive_strong_answers", 0)
        req_skills_cov = st.get("required_skills_covered", False)
    else:
        q_asked = int(interview_state_or_count)
        min_q = min_questions
        max_q = max_questions
        c_stages = covered_stages or []
        c_topics = covered_topics or []
        r_scores = recent_scores or []
        w_answers = consecutive_weak_answers
        s_answers = consecutive_strong_answers
        req_skills_cov = False

    if q_asked < min_q:
        return False, f"Minimum boundary not reached ({q_asked}/{min_q})"
    if q_asked >= max_q:
        return True, f"Maximum dynamic question limit reached ({max_q})"

    stages = set(s.upper() for s in c_stages)
    topics = set(c_topics)

    # Check key stages
    has_intro = any("INTRO" in s for s in stages)
    has_tech = any("TECHNICAL" in s or "FUNDAMENTAL" in s for s in stages)
    has_project = any("PROJECT" in s for s in stages)
    has_advanced = any("ADVANCED" in s or "SCENARIO" in s for s in stages)

    # Need core stages covered and at least 3 distinct topics evaluated
    if (has_intro and has_tech and has_project and len(topics) >= 3) or req_skills_cov:
        if s_answers >= 2 or len(r_scores) >= 5 or req_skills_cov:
            return True, "Comprehensive assessment reached across all target competencies."
        if w_answers >= 2 and q_asked >= 8:
            return True, "Sufficient diagnostic signal collected across evaluated competency boundaries."
        if q_asked >= 10:
            return True, "Thorough evaluation completed across all planned technical and project competencies."

    return False, "Additional questions provide valuable signal on remaining competency areas."


@timed("adaptive.decision")
def decide_next_action(
    evaluation: AdaptiveEvaluationInput,
    previous_question: str,
    category: str = "Technical",
    difficulty: InterviewDifficulty = "Medium",
    relevant_skills: list[str] | None = None,
    current_topic: str = "General",
    consecutive_follow_ups: int = 0,
    answer_history: list[dict[str, Any]] | None = None,
    question_history: list[str] | None = None,
    candidate_answer: str = "",
    allow_recovery: bool = False,
    current_stage: str = "TECHNICAL_FUNDAMENTALS",
    interview_mode: str = "STATIC",
    questions_asked: int = 0,
    min_questions: int = 5,
    max_questions: int = 20,
    covered_stages: list[str] | None = None,
    covered_topics: list[str] | None = None,
    allow_background_follow_up: bool = True,
) -> AdaptiveDecisionResult:
    """
    Deterministic decision layer for adaptive interviewing.
    Considers conceptual correctness, relevance, clarity and answer status,
    question context, session history, and dynamic/static interview bounds.
    Does NOT depend on an LLM call.
    """
    skills = relevant_skills or []
    target_skill = skills[0] if skills else current_topic
    answer_hist = answer_history or []
    curr_diff: InterviewDifficulty = difficulty if difficulty in DIFFICULTY_LEVELS else "Medium"

    # 0. Session Stopping Boundary Checks
    if interview_mode == "DYNAMIC":
        if questions_asked >= max_questions:
            return AdaptiveDecisionResult(
                decision="END_INTERVIEW",
                reason=f"Reached maximum question safety boundary ({max_questions} questions) for dynamic interview.",
                target_skill=target_skill,
                target_concept="interview conclusion",
                difficulty=curr_diff,
                next_difficulty=curr_diff,
                is_follow_up=False,
                end_interview=True,
            )
        if questions_asked >= min_questions:
            scores = []
            for a in answer_hist:
                if isinstance(a, dict) and "evaluation" in a and isinstance(a["evaluation"], dict):
                    scores.append(int(a["evaluation"].get("score", 70)))
            if not scores:
                scores = [evaluation.score]
            should_end, end_reason = should_end_dynamic_session(
                interview_state_or_count=questions_asked,
                min_questions=min_questions,
                max_questions=max_questions,
                covered_stages=covered_stages,
                covered_topics=covered_topics,
                recent_scores=scores,
            )
            if should_end:
                return AdaptiveDecisionResult(
                    decision="END_INTERVIEW",
                    reason=end_reason,
                    target_skill=target_skill,
                    target_concept="interview conclusion",
                    difficulty=curr_diff,
                    next_difficulty=curr_diff,
                    is_follow_up=False,
                    end_interview=True,
                )
    elif interview_mode == "STATIC":
        if max_questions > 0 and questions_asked >= max_questions:
            return AdaptiveDecisionResult(
                decision="END_INTERVIEW",
                reason=f"Reached selected maximum question count ({max_questions}) for static interview.",
                target_skill=target_skill,
                target_concept="interview conclusion",
                difficulty=curr_diff,
                next_difficulty=curr_diff,
                is_follow_up=False,
                end_interview=True,
            )

    # 0a. RULE: Introduction Question Stage
    is_intro = (
        "intro" in current_topic.lower()
        or current_stage.upper() in ("INTRO", "INTRODUCTION")
        or "introduce yourself" in previous_question.lower()
        or "walk me through your background" in previous_question.lower()
    )
    if is_intro:
        clean_ans = candidate_answer.strip().lower()
        is_name_only = (
            bool(re.search(r"^(my\s+name\s+is|i\s+am|myself)\s+[a-zA-Z\s]+$", clean_ans))
            or (len(clean_ans.split()) <= 6 and clean_ans and not any(w in clean_ans for w in ["b.tech", "student", "experience", "degree", "worked", "java", "python", "developer", "engineer"]))
        )
        is_partial_eval = evaluation.answer_status != "CORRECT" and (
            evaluation.technicalAccuracy < 60 or evaluation.relevance <= 40
            or any("background" in imp.lower() or "education" in imp.lower() for imp in evaluation.improvements)
        )

        if allow_background_follow_up and (is_name_only or is_partial_eval) and consecutive_follow_ups < MAX_CONSECUTIVE_FOLLOWUPS:
            lead = "Sure"
            name_match = re.search(r"(?:my\s+name\s+is|i\s+am|myself)?\s*([a-zA-Z]+)", candidate_answer.strip(), re.IGNORECASE)
            if name_match:
                extracted_name = name_match.group(1).capitalize()
                if extracted_name.lower() not in ("my", "name", "is", "i", "am", "myself"):
                    lead = f"Sure, {extracted_name}"

            return AdaptiveDecisionResult(
                decision="TARGETED_FOLLOW_UP",
                reason="Candidate provided their name. Requesting educational background and technical interests.",
                target_skill="Background & Experience",
                target_concept="educational background and key technologies",
                difficulty=curr_diff,
                next_difficulty=curr_diff,
                is_follow_up=True,
                conversational_lead_in=lead,
            )
        else:
            return AdaptiveDecisionResult(
                decision="NEXT_TOPIC",
                reason="Candidate introduction complete. Advancing to resume and technical fundamentals.",
                target_skill=target_skill,
                target_concept="next planned topic",
                difficulty=curr_diff,
                next_difficulty=curr_diff,
                is_follow_up=False,
                conversational_lead_in="Thank you for the introduction.",
            )

    # 0b. RULE: Explicit Non-Answer ("I don't know", etc.)
    is_non_answer = (
        (evaluation.score == 0 and evaluation.technicalAccuracy == 0 and evaluation.relevance == 0)
        or any("does not attempt to answer" in imp.lower() for imp in evaluation.improvements)
        or (bool(candidate_answer.strip()) and is_explicit_non_answer(candidate_answer))
    )
    if is_non_answer:
        if allow_recovery and consecutive_follow_ups < MAX_CONSECUTIVE_FOLLOWUPS:
            return AdaptiveDecisionResult(
                decision="RECOVERY_QUESTION",
                reason="Candidate indicated they are unsure. Stepping back to core prerequisite fundamentals before moving on.",
                target_skill=target_skill,
                target_concept=f"fundamental concepts of {target_skill}",
                difficulty=curr_diff,
                next_difficulty=curr_diff,
                is_follow_up=True,
                conversational_lead_in="That's okay. Let's start with the basics.",
            )
        else:
            return AdaptiveDecisionResult(
                decision="NEXT_TOPIC",
                reason="Candidate indicated they do not know or reached follow-up limit. Advancing to next topic without endless drilling.",
                target_skill=target_skill,
                target_concept="next planned topic",
                difficulty=curr_diff,
                next_difficulty=curr_diff,
                is_follow_up=False,
            )

    # 1. RULE: Maximum Consecutive Follow-ups Limit
    if consecutive_follow_ups >= MAX_CONSECUTIVE_FOLLOWUPS:
        return AdaptiveDecisionResult(
            decision="NEXT_TOPIC",
            reason=f"Reached maximum consecutive follow-ups ({MAX_CONSECUTIVE_FOLLOWUPS}) on '{current_topic}'. Advancing to next topic.",
            target_skill=target_skill,
            target_concept="next planned topic",
            difficulty=curr_diff,
            next_difficulty=curr_diff,
            is_follow_up=False,
        )

    # 2. RULE: Off-topic / Low Relevance (relevance <= 40)
    if evaluation.relevance <= 40:
        return AdaptiveDecisionResult(
            decision="TARGETED_FOLLOW_UP",
            reason=f"Answer relevance was low ({evaluation.relevance}/100) and drifted off-topic. Clarification requested to refocus candidate.",
            target_skill=target_skill,
            target_concept=f"core principles of {target_skill}",
            difficulty=curr_diff,
            next_difficulty=curr_diff,
            is_follow_up=True,
        )

    # 3. RULE: Probe a meaningful gap in the requested concepts.
    if evaluation.technicalAccuracy < 60:
        concept = _extract_target_concept(evaluation, target_skill)
        return AdaptiveDecisionResult(
            decision="TARGETED_FOLLOW_UP",
            reason=f"Technical accuracy ({evaluation.technicalAccuracy}/100) indicates gaps or misconceptions in {concept}.",
            target_skill=target_skill,
            target_concept=concept,
            difficulty=curr_diff,
            next_difficulty=curr_diff,
            is_follow_up=True,
        )

    # 5. RULE: Strong Technical Correctness but Poor Clarity (tech >= 75, clarity < 55)
    if (evaluation.technicalAccuracy >= 75 and evaluation.clarity < 55
            and len(conceptual_feedback(evaluation.improvements)) == len(evaluation.improvements)):
        return AdaptiveDecisionResult(
            decision="TARGETED_FOLLOW_UP",
            reason=f"Demonstrated technical understanding ({evaluation.technicalAccuracy}/100) but lacked clarity ({evaluation.clarity}/100). Requesting structured explanation.",
            target_skill=target_skill,
            target_concept=f"structured explanation of {target_skill}",
            difficulty=curr_diff,
            next_difficulty=curr_diff,
            is_follow_up=True,
        )

    # 6. RULE: Strong conceptual performance earns a harder probe.
    if performance_level(evaluation) == "strong" and evaluation.relevance >= 85:
        preceding = [
            a["evaluation"] for a in answer_hist
            if isinstance(a, dict) and isinstance(a.get("evaluation"), dict)
        ]
        is_consistently_strong = curr_diff == "Easy" or bool(
            preceding and performance_level(AdaptiveEvaluationInput.model_validate(preceding[-1])) == "strong"
        )

        if is_consistently_strong and curr_diff != "Hard":
            next_diff: InterviewDifficulty = "Medium" if curr_diff == "Easy" else "Hard"
            return AdaptiveDecisionResult(
                decision="ADVANCE_DIFFICULTY",
                reason=f"Consistently strong conceptual understanding. Advancing difficulty from {curr_diff} to {next_diff}.",
                target_skill=target_skill,
                target_concept=f"advanced {target_skill} architecture and optimization",
                difficulty=curr_diff,
                next_difficulty=next_diff,
                is_follow_up=False,
            )
        else:
            return AdaptiveDecisionResult(
                decision="DEEPER_CHALLENGE",
                reason=f"Strong answer ({evaluation.score}/100). Probing deeper into advanced scenarios, concurrency, and trade-offs.",
                target_skill=target_skill,
                target_concept=f"advanced {target_skill} scenarios and trade-offs",
                difficulty=curr_diff,
                next_difficulty=curr_diff,
                is_follow_up=True,
            )

    # 7. RULE: Satisfactory Answer -> Move to next planned topic
    return AdaptiveDecisionResult(
        decision="NEXT_TOPIC",
        reason=f"Answer is satisfactory ({evaluation.score}/100). Transitioning to next planned topic.",
        target_skill=target_skill,
        target_concept="next planned topic",
        difficulty=curr_diff,
        next_difficulty=curr_diff,
        is_follow_up=False,
    )


def generate_fallback_question(
    decision: AdaptiveDecisionType,
    target_skill: str,
    target_concept: str,
    difficulty: InterviewDifficulty,
    category: str = "Technical",
    subject: str | None = None,
    history: list[str] | None = None,
) -> GeneratedQuestion:
    """
    Deterministic fallback question generator if Qwen3 is offline, times out,
    or fails duplicate checks after max retries.
    Validates category, subject, and duplicate constraints.
    """
    if category != "Technical":
        raise LLMResponseParseError("A valid category question could not be generated. Please retry.")

    skill_label = target_skill
    if subject and not subject_matches(skill_label, subject):
        skill_label = f"{subject} ({target_skill})"

    templates: list[tuple[str, str]] = []
    if decision == "TARGETED_FOLLOW_UP":
        templates = [
            (f"Could you elaborate more specifically on how you handle {target_concept} in {skill_label}, including practical trade-offs or constraints?", "Targeted Follow-up"),
            (f"Could you explain the underlying mechanism and common pitfalls when working with {target_concept} in {skill_label}?", "Targeted Follow-up"),
            (f"What specific debugging or optimization techniques would you apply when encountering issues with {target_concept} in {skill_label}?", "Targeted Follow-up"),
        ]
    elif decision == "RECOVERY_QUESTION":
        templates = [
            (f"That's completely okay. Let's start with the core basics: what is your fundamental understanding of {target_concept} in {skill_label}?", "Recovery Question"),
            (f"Let's break this down to the essentials: how would you define the basic role of {target_concept} in {skill_label}?", "Recovery Question"),
            (f"Could you describe a simple, real-world example of how {target_concept} is used in {skill_label}?", "Recovery Question"),
        ]
    elif decision == "DEEPER_CHALLENGE":
        templates = [
            (f"In a high-throughput production environment, what specific edge cases or failure modes would you anticipate when working with {target_concept} in {skill_label}, and how would you mitigate them?", "Deeper Challenge"),
            (f"How would you optimize performance and ensure fault tolerance when designing {target_concept} in {skill_label} under scale?", "Deeper Challenge"),
            (f"What architectural trade-offs must be evaluated when scaling {target_concept} in {skill_label} across distributed services?", "Deeper Challenge"),
        ]
    else:
        templates = [
            (f"Can you walk through your design approach for {target_concept} in {skill_label}, highlighting key architectural considerations?", "Advanced Question"),
            (f"What are the key trade-offs and best practices when implementing {target_concept} in {skill_label}?", "Advanced Question"),
            (f"How would you explain the core architecture and practical usage of {target_concept} in {skill_label}?", "Core Fundamentals"),
        ]

    # Validate against category, subject, and duplicate constraints
    hist = history or []
    chosen_text = None
    chosen_focus = None
    for text, focus in templates:
        if not category_matches(text, category, allow_opening=False):
            continue
        if WORDING_QUESTION.search(text) and not WORDING_QUESTION.search(target_skill):
            continue
        if subject and not subject_matches(text, subject):
            continue
        if hist:
            if is_duplicate_question(text, hist, allow_opening=False):
                continue
            if semantic_duplicate(text, hist):
                continue
        chosen_text = text
        chosen_focus = focus
        break

    if not chosen_text:
        raise LLMResponseParseError("The fallback generator could not produce a unique question within the requested scope. Please retry.")

    q_id = f"adaptive-{int(time.time() * 1000)}"
    return GeneratedQuestion(
        id=q_id,
        question=chosen_text,
        category="HR" if category == "HR" else "Technical",
        topic=target_skill,
        difficulty=difficulty,
        focus=chosen_focus,
        expected_aspects=[f"Clear mechanics of {target_concept}", "Discussion of constraints or trade-offs"],
    )


def create_interview_plan(
    candidate_profile: dict[str, Any] | CandidateProfile | None = None,
    job_profile: dict[str, Any] | JobProfile | None = None,
    analysis: dict[str, Any] | None = None,
    interview_type: str = "Technical",
    difficulty: str = "Medium",
    interview_mode: str = "STATIC",
    question_count: int = 10,
    role: str = "Software Engineer",
    subject: str | None = None,
) -> dict[str, Any]:
    """
    Constructs a structured interview plan separating WHAT should be assessed from
    HOW questions are phrased.
    Prioritizes resume skills and JD gaps intelligently without random repetition of REST/DB/System Design.
    """
    c_dict = (candidate_profile if isinstance(candidate_profile, dict) else (candidate_profile.model_dump() if candidate_profile else {})) or {}
    j_dict = (job_profile if isinstance(job_profile, dict) else (job_profile.model_dump() if job_profile else {})) or {}

    cand_name = str(c_dict.get("candidate_name") or c_dict.get("name") or "").strip()
    resume_skills = [str(s).strip() for s in (c_dict.get("extracted_skills") or c_dict.get("skills") or []) if str(s).strip()]
    jd_skills = [str(s).strip() for s in (j_dict.get("required_skills") or j_dict.get("technical_skills") or j_dict.get("skills") or []) if str(s).strip()]

    analysis_dict = analysis if isinstance(analysis, dict) else (analysis.model_dump() if analysis else {})
    matched_skills = analysis_dict.get("skills_found", []) or [s for s in resume_skills if any(s.lower() == j.lower() for j in jd_skills)]
    gap_skills = analysis_dict.get("gap_skills", []) or [s for s in jd_skills if not any(s.lower() == r.lower() for r in resume_skills)]

    raw_projects = c_dict.get("key_projects") or c_dict.get("projects") or []
    projects: list[dict[str, Any]] = []
    for p in raw_projects:
        if isinstance(p, dict):
            projects.append(p)
        elif hasattr(p, "model_dump"):
            projects.append(p.model_dump())
        elif isinstance(p, str):
            projects.append({"name": p, "description": p})

    # Build prioritized skills list (Resume Primary -> Matched Core -> JD Gaps -> Secondary)
    prioritized_skills: list[str] = []
    for s in matched_skills:
        if s not in prioritized_skills:
            prioritized_skills.append(s)
    for s in resume_skills:
        if s not in prioritized_skills:
            prioritized_skills.append(s)
    for s in gap_skills:
        if s not in prioritized_skills:
            prioritized_skills.append(s)
    if not prioritized_skills:
        prioritized_skills = ["Core Programming", "Software Architecture", "Problem Solving"]

    # Plan stages progression
    if interview_mode == "STATIC" and question_count == 5:
        stages_planned = [
            "INTRO",
            "RESUME_BACKGROUND",
            "TECHNICAL_FUNDAMENTALS",
            "PROJECT_INTRO",
            "ADVANCED_SCENARIO",
        ]
    elif interview_mode == "STATIC" and question_count == 10:
        stages_planned = [
            "INTRO",
            "RESUME_BACKGROUND",
            "TECHNICAL_FUNDAMENTALS",
            "TECHNICAL_DISCUSSION",
            "PROJECT_INTRO",
            "PROJECT_DEEP_DIVE",
            "JD_FUNDAMENTALS",
            "ADVANCED_SCENARIO",
            "ADVANCED_SCENARIO",
            "FINAL_ADAPTIVE",
        ]
    elif interview_mode == "STATIC" and question_count >= 15:
        stages_planned = [
            "INTRO",
            "RESUME_BACKGROUND",
            "TECHNICAL_FUNDAMENTALS",
            "TECHNICAL_FUNDAMENTALS",
            "TECHNICAL_DISCUSSION",
            "PROJECT_INTRO",
            "PROJECT_DEEP_DIVE",
            "PROJECT_DEEP_DIVE",
            "JD_FUNDAMENTALS",
            "JD_FUNDAMENTALS",
            "ADVANCED_SCENARIO",
            "ADVANCED_SCENARIO",
            "ADVANCED_SCENARIO",
            "FINAL_ADAPTIVE",
            "FINAL_ADAPTIVE",
        ]
        if question_count == 20:
            stages_planned.extend(["ADVANCED_SCENARIO", "PROJECT_DEEP_DIVE", "JD_FUNDAMENTALS", "FINAL_ADAPTIVE", "FINAL_ADAPTIVE"])
    else:  # DYNAMIC mode default stages
        stages_planned = [
            "INTRO",
            "RESUME_BACKGROUND",
            "TECHNICAL_FUNDAMENTALS",
            "TECHNICAL_DISCUSSION",
            "PROJECT_INTRO",
            "PROJECT_DEEP_DIVE",
            "JD_FUNDAMENTALS",
            "ADVANCED_SCENARIO",
            "FINAL_ADAPTIVE",
        ]

    if interview_type in ("HR", "Mixed"):
        count = question_count if interview_mode == "STATIC" else MAX_DYNAMIC_QUESTIONS
        schedule = category_schedule(interview_type, count)
        stages_planned = ["INTRO"] + ["BEHAVIORAL" if c == "HR" else "TECHNICAL_FUNDAMENTALS" for c in schedule[1:]]
        if interview_type == "HR":
            prioritized_skills = list(HR_TOPICS)
    elif subject:
        prioritized_skills = list(SUBJECT_TOPICS[subject])
        random.SystemRandom().shuffle(prioritized_skills)
        stages_planned = ["TECHNICAL_FUNDAMENTALS"] * (question_count if interview_mode == "STATIC" else MAX_DYNAMIC_QUESTIONS)
    else:
        stages_planned = [s for s in stages_planned if s != "RESUME_BACKGROUND"]
        stages_planned.append("FINAL_ADAPTIVE")

    planned_sequence = []
    for i, stg in enumerate(stages_planned):
        skill = prioritized_skills[i % len(prioritized_skills)] if prioritized_skills else "General"
        planned_sequence.append({
            "stage": stg,
            "topic": "Candidate Introduction" if stg == "INTRO" else (projects[0].get("name", "Project Experience") if "PROJECT" in stg and projects else skill),
            "difficulty": "Easy" if stg == "INTRO" else ("Hard" if "ADVANCED" in stg else "Medium"),
        })
    schedule = category_schedule(interview_type, question_count if interview_mode == "STATIC" else MAX_DYNAMIC_QUESTIONS)
    for i, entry in enumerate(planned_sequence):
        entry["category"] = schedule[i % len(schedule)]
        if interview_type in ("HR", "Mixed") and i and entry["category"] == "HR":
            entry["topic"] = HR_TOPICS[(i - 1) % len(HR_TOPICS)]

    return {
        "mode": interview_mode,
        "interview_mode": interview_mode,
        "total_questions": len(stages_planned),
        "max_questions": question_count if interview_mode == "STATIC" else MAX_DYNAMIC_QUESTIONS,
        "min_questions": MIN_DYNAMIC_QUESTIONS if interview_mode == "DYNAMIC" else min(MIN_DYNAMIC_QUESTIONS, question_count),
        "current_stage": stages_planned[0],
        "subject": subject,
        "category_schedule": schedule,
        "current_stage_index": 0,
        "stages_planned": stages_planned,
        "planned_sequence": planned_sequence,
        "candidate_name": cand_name,
        "role": role or j_dict.get("role_title") or j_dict.get("title") or "Software Engineer",
        "interview_type": interview_type,
        "difficulty": difficulty,
        "target_skills": prioritized_skills,
        "skills_priority": prioritized_skills,
        "candidate_projects": projects,
        "active_project": projects[0] if projects else None,
        "project_question_step": 0,
    }


def create_initial_interview_state(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Initializes runtime tracking state for the active interview."""
    return {
        "questions_asked": 0,
        "current_stage": (plan or {}).get("current_stage", "INTRO"),
        "current_topic": ((plan or {}).get("skills_priority") or ["Candidate Introduction"])[0] if (plan or {}).get("subject") else "Candidate Introduction",
        "subject": (plan or {}).get("subject"),
        "interview_type": (plan or {}).get("interview_type"),
        "category_counts": {"HR": 0, "Technical": 0},
        "current_difficulty": "Easy" if (plan or {}).get("difficulty") == "Easy" else "Medium",
        "covered_stages": [],
        "covered_topics": [],
        "covered_skills": [],
        "weak_areas": [],
        "strong_areas": [],
        "consecutive_weak_answers": 0,
        "consecutive_strong_answers": 0,
        "recent_scores": [],
        "consecutive_follow_ups": 0,
        "follow_ups_used": 0,
        "required_skills_covered": False,
        "last_answer_status": None,
        "last_decision": None,
    }


def create_first_question(
    candidate_name: str | None = None,
    interview_type: str = "Technical",
    role: str | None = None,
) -> GeneratedQuestion:
    """Creates the standard, warm opening Question 1 in 0ms without waiting for Ollama."""
    name_str = f"Hi {candidate_name.strip()}, " if candidate_name and candidate_name.strip() else "Hi, "
    q_text = f"{name_str}could you please introduce yourself and briefly walk me through your background?"
    return GeneratedQuestion(
        id="q1",
        question=q_text,
        category="HR" if interview_type in ("HR", "Mixed") else "Technical",
        topic="Candidate Introduction",
        difficulty="Easy",
        stage="INTRO",
        focus="Introduction",
        expected_aspects=[
            "Structured overview of education and professional background",
            "Summary of core technical competencies and areas of interest",
        ],
    )


@timed("question.generate")
@llm_usage.operation(lambda *args, **kw: "initial_question" if kw.get("q_index") == 1 else "adaptive_question")
async def generate_single_next_question(
    decision: AdaptiveDecisionType,
    stage: str,
    target_skill: str,
    target_concept: str,
    difficulty: InterviewDifficulty,
    category: str,
    role: str,
    previous_question: str | None = None,
    candidate_answer: str | None = None,
    candidate_name: str | None = None,
    project_name: str | None = None,
    conversational_instruction: str = "",
    question_history: list[str] | None = None,
    q_index: int = 2,
    subject: str | None = None,
    evaluation: AdaptiveEvaluationInput | None = None,
    answer_history: list[dict] | None = None,
    allow_opening: bool = False,
    project_context: dict | None = None,
) -> tuple[GeneratedQuestion, str]:
    """
    Generates exactly ONE natural interview question via Qwen3 with low latency (~50-80 tokens).
    Extracts conversational lead-in and validates against duplicates.
    """
    history = list(question_history or [])
    if previous_question and previous_question not in history:
        history.append(previous_question)
    supplied_projects = named_projects([project_context or {"name": project_name}])
    project = supplied_projects[0] if supplied_projects else None
    project_specific = not subject and ("PROJECT" in stage or
        (decision in FOLLOW_UPS and (project is not None or refers_to_project(previous_question))))
    if subject or (not project_specific and category != "HR"):
        project = None
    prompt_started = time.perf_counter()
    prompt = build_single_question_prompt(
        role=role,
        stage=stage,
        target_skill=target_skill,
        target_topic=target_skill,
        target_concept=target_concept,
        difficulty=difficulty,
        decision=decision,
        previous_question=previous_question,
        candidate_answer=candidate_answer,
        candidate_name=candidate_name,
        project_name=project["name"] if project else None,
        project_context=project,
        conversational_instruction=conversational_instruction,
        question_history=history,
        subject=subject,
        evaluation=evaluation.model_dump(exclude={"suggestedAnswer"}) if evaluation else None,
        answer_history=answer_history,
        allow_opening=allow_opening,
        category=category,
    )

    metric("question.prompt", duration_ms=(time.perf_counter() - prompt_started) * 1000)
    # History embeddings are independent of the generated question and its evaluation.
    vectors_by_text = {}
    history_ready = asyncio.create_task(asyncio.to_thread(prepare_semantic_history, history, vectors_by_text))
    validity = {}
    last_reject_reason = None
    tests_wording = bool(WORDING_QUESTION.search(target_skill))
    @timed("question.validation")
    async def valid(text, source=None):
        nonlocal last_reject_reason
        await history_ready
        key = (text, source, decision)
        if key not in validity:
            reason = ("missing_question" if not text or len(text) < 12 else
                      "opening" if not allow_opening and is_opening(text) else
                      "category" if not category_matches(text, category, allow_opening) else
                      "subject" if not subject_matches(text, subject) else
                      "wording_only" if not tests_wording and WORDING_QUESTION.search(text) else
                      "unconnected_follow_up" if category == "HR" and decision in FOLLOW_UPS
                          and not (project_specific and not project)
                          and not grounded_hr_follow_up(source or text, previous_question, candidate_answer, project,
                                                       recovery=decision == "RECOVERY_QUESTION") else
                      "duplicate" if is_duplicate_question(text, history, allow_opening=allow_opening) else
                      "semantic_duplicate" if await asyncio.to_thread(semantic_duplicate, text, history, vectors_by_text) else None)
            validity[key] = reason is None
            if reason:
                last_reject_reason = reason
                logger.warning("question_rejected reason=%s category=%s history_count=%d", reason, category, len(history))
        return validity[key]

    try:
        q_text = ""
        lead_in = ""
        for attempt in range(MAX_GENERATION_RETRIES + 1):
            metric("question.attempt", attempt=attempt + 1)
            if attempt:
                if last_reject_reason == "subject":
                    retry_note = (f"\nPrevious output was rejected because the question text did not explicitly mention "
                                  f"the required subject '{subject}'. You MUST include the exact keyword '{subject}' "
                                  f"in the question text. Generate a completely different question. Return valid JSON.")
                elif last_reject_reason in ("duplicate", "semantic_duplicate"):
                    retry_note = (f"\nPrevious output was rejected because it duplicated a question already asked. "
                                  f"The rejected question was: {q_text!r}. Generate a question on a DIFFERENT aspect "
                                  f"of the topic. Return valid JSON.")
                elif last_reject_reason == "category":
                    retry_note = (
                        "\nAsk explicitly about the person's actions with teammates, feedback, priorities or professional judgment within the target topic."
                        if category == "HR" else "\nAsk a clearly technical question about the requested subject."
                    )
                elif last_reject_reason == "unconnected_follow_up":
                    retry_note = "\nKeep the same scenario and name a specific decision or action from the last answer or question."
                elif last_reject_reason == "wording_only":
                    retry_note = "\nAsk how the concept works or how to apply it. Do not quiz spelling, pronunciation or transcription."
                else:
                    retry_note = (f"\nPrevious output was invalid or out of scope. "
                                  f"Generate a different question from: {q_text!r}. Return complete valid JSON.")
            else:
                retry_note = ""
            try:
                output = await llm_service.generate_json_response(
                    prompt=prompt + retry_note, think=False, num_predict=120,
                    temperature=min(0.2 + attempt * 0.15, 0.7))
            except LLMResponseParseError:
                last_reject_reason = "invalid_json"
                logger.warning("question_rejected reason=invalid_json category=%s history_count=%d", category, len(history))
                if attempt < MAX_GENERATION_RETRIES or category == "HR":
                    continue
                raise
            if isinstance(output, dict) and isinstance(output.get("questions"), list):
                output = output["questions"]
            if isinstance(output, list):
                output = output[0] if output else {}
            data = output if isinstance(output, dict) else {}
            source = str(data.get("question") or "").strip()
            q_text = explicit_project_question(source, project, required=project_specific, category=category)
            lead_in = str(data.get("lead_in") or data.get("acknowledgment") or "").strip()
            if await valid(q_text, source):
                if "?" in lead_in or (category == "HR" and question_intent(lead_in) == "Technical"):
                    lead_in = ""  # A segue must not introduce a second assessment.
                break
        else:
            if category != "HR":
                raise LLMResponseParseError("The model could not produce a unique question within the requested scope. Please retry.")
            candidates = ((decision, text, topic)
                          for text, topic in hr_fallback_candidates(target_skill, decision, previous_question, project))
            if decision in FOLLOW_UPS:
                next_topics = (("NEXT_TOPIC", text, topic) for text, topic in
                               hr_fallback_candidates("", "NEXT_TOPIC", None, project) if topic != target_skill)
                candidates = chain(candidates, next_topics)
            for candidate_decision, text, topic in candidates:
                if candidate_decision != decision:
                    decision = candidate_decision
                    project_specific = False
                text = explicit_project_question(text, project, required=project_specific, category=category)
                if await valid(text):
                    q_text, target_skill, lead_in = text, topic, ""
                    logger.warning("question_fallback_used category=HR")
                    metric("question.fallback", count=1)
                    break
            else:
                raise LLMResponseParseError("A distinct behavioral question could not be generated within this interview's scope.")

        # Ensure question has proper ID and focus
        focus_label = (
            "Targeted Follow-up" if decision == "TARGETED_FOLLOW_UP"
            else "Recovery Question" if decision == "RECOVERY_QUESTION"
            else "Deeper Challenge" if decision == "DEEPER_CHALLENGE"
            else "Project Discussion" if "PROJECT" in stage
            else "Core Fundamentals"
        )

        stage_norm: InterviewStage = "INTRO" if stage == "INTRO" else (
            "ADAPTIVE" if category == "HR" else ("PROJECT" if "PROJECT" in stage else "TECHNICAL_FUNDAMENTALS"))

        gen_q = GeneratedQuestion(
            id=f"q{q_index}",
            question=q_text,
            category="HR" if category == "HR" else "Technical",
            topic=project["name"] if category != "HR" and "PROJECT" in stage and project else target_skill,
            difficulty=difficulty,
            stage=stage_norm,
            is_follow_up=(decision in ("TARGETED_FOLLOW_UP", "RECOVERY_QUESTION", "DEEPER_CHALLENGE")),
            focus=focus_label,
            expected_aspects=(["Address the specific question asked", "Support explanations with relevant evidence; do not invent personal experience"] if project_specific else
                (["Specific personal actions", "Communication, outcomes and reflection"] if category == "HR" else [f"Clear mechanics of {target_concept}", "Practical examples or constraints"])),
        )
        return gen_q, lead_in

    except (LLMResponseParseError, OllamaConnectionError, OllamaTimeoutError, OllamaModelNotFoundError):
        raise
    except Exception as exc:
        logger.error("question_generation_failed exception_type=%s", type(exc).__name__)
        raise
    finally:
        if not history_ready.done(): history_ready.cancel()
        try: await history_ready
        except asyncio.CancelledError: pass



@llm_usage.operation("interview_start")
async def process_adaptive_start(request: InterviewStartRequest) -> InterviewStartResponse:
    """
    POST /api/v1/interview/start
    Instantly initializes an interview session and interview plan, returning ONLY Question 1.
    """
    start_time = time.perf_counter()
    cand_profile = request.candidate_profile
    job_profile = request.job_profile
    cand_name = cand_profile.get("candidate_name") if isinstance(cand_profile, dict) else getattr(cand_profile, "candidate_name", "")

    plan = create_interview_plan(
        candidate_profile=cand_profile,
        job_profile=job_profile,
        analysis=request.analysis,
        interview_type=request.interview_type,
        difficulty=request.difficulty,
        interview_mode=request.interview_mode,
        question_count=request.question_count,
        role=request.role,
        subject=request.subject,
    )
    state = create_initial_interview_state(plan)
    if request.subject:
        first_q, _ = await generate_single_next_question(
            decision="NEXT_TOPIC", stage="TECHNICAL_FUNDAMENTALS",
            target_skill=plan["skills_priority"][0], target_concept=plan["skills_priority"][0],
            difficulty=state["current_difficulty"], category="Technical", role=request.role,
            subject=request.subject, q_index=1)
    else:
        first_q = create_first_question(cand_name, request.interview_type)
    state["questions_asked"] = 1
    state["category_counts"][first_q.category] = 1
    state["covered_stages"].append(first_q.stage)
    state["covered_topics"].append(first_q.topic)

    now_ms = int(time.time() * 1000)
    session_id = f"session-{now_ms}-{hash(cand_name) % 10000:04d}"
    state["session_id"] = session_id
    plan["session_id"] = session_id
    elapsed_ms = round((time.perf_counter() - start_time) * 1000)

    return InterviewStartResponse(
        session_id=session_id,
        interview_mode=request.interview_mode,
        interview_plan=plan,
        interview_state=state,
        first_question=first_q,
        processing_time_ms=elapsed_ms,
    )


@llm_usage.operation("legacy_adaptive_question")
async def execute_adaptive_generation(
    decision_result: AdaptiveDecisionResult,
    previous_question: str,
    candidate_answer: str,
    evaluation: AdaptiveEvaluationInput,
    category: str,
    role: str,
    question_history: list[str],
) -> GeneratedQuestion:
    """
    Legacy generation helper kept for backward compatibility with Phase 9 unit tests.
    """
    all_history = list(question_history)
    if previous_question and previous_question not in all_history:
        all_history.append(previous_question)

    effective_difficulty = (
        decision_result.next_difficulty
        if decision_result.decision == "ADVANCE_DIFFICULTY"
        else decision_result.difficulty
    )

    last_error: Exception | None = None
    retry_hint: str | None = None
    is_malformed_retry: bool = False
    malformed_reason: str = "malformed JSON"

    for attempt in range(MAX_GENERATION_RETRIES + 1):
        if attempt == 0:
            prompt = build_adaptive_followup_prompt(
                decision=decision_result.decision,
                previous_question=previous_question,
                candidate_answer=candidate_answer,
                evaluation=evaluation,
                target_skill=decision_result.target_skill,
                target_concept=decision_result.target_concept,
                category=category,
                difficulty=effective_difficulty,
                role=role,
                question_history=all_history,
                retry_duplicate_hint=None,
            )
            temp = 0.2
            num_tokens = 350
        else:
            if is_malformed_retry:
                prompt = build_adaptive_retry_prompt(
                    role=role,
                    target_skill=decision_result.target_skill,
                    target_concept=decision_result.target_concept,
                    difficulty=effective_difficulty,
                    category=category,
                    error_reason=malformed_reason,
                )
            else:
                prompt = build_adaptive_followup_prompt(
                    decision=decision_result.decision,
                    previous_question=previous_question,
                    candidate_answer=candidate_answer,
                    evaluation=evaluation,
                    target_skill=decision_result.target_skill,
                    target_concept=decision_result.target_concept,
                    category=category,
                    difficulty=effective_difficulty,
                    role=role,
                    question_history=all_history,
                    retry_duplicate_hint=retry_hint,
                )
            temp = 0.1
            num_tokens = 300

        try:
            llm_output = await llm_service.generate_json_response(
                prompt=prompt,
                think=False,
                num_predict=num_tokens,
                temperature=temp,
            )

            # Extract fields safely
            data = llm_output
            if isinstance(data, dict) and "questions" in data and isinstance(data["questions"], list) and len(data["questions"]) > 0:
                data = data["questions"][0]

            if not isinstance(data, dict):
                raise llm_service.LLMResponseParseError("Expected dictionary output")

            q_text = str(data.get("question") or data.get("followUpQuestion") or "").strip()
            if not q_text or len(q_text) < 10:
                raise llm_service.LLMResponseParseError("Question missing or too short")
            if not category_matches(q_text, category):
                raise llm_service.LLMResponseParseError("Question does not match the required category")
            if WORDING_QUESTION.search(q_text) and not WORDING_QUESTION.search(decision_result.target_skill):
                raise llm_service.LLMResponseParseError("Ask how the concept works or how to apply it, without a spelling quiz.")

            if is_duplicate_question(q_text, all_history):
                if attempt < MAX_GENERATION_RETRIES:
                    retry_hint = q_text
                    is_malformed_retry = False
                    continue
                raise llm_service.LLMResponseParseError(f"Duplicate question generated: '{q_text}'")

            q_id = f"adaptive-{int(time.time() * 1000)}"
            focus_label = (
                "Targeted Follow-up"
                if decision_result.decision == "TARGETED_FOLLOW_UP"
                else "Deeper Challenge"
                if decision_result.decision == "DEEPER_CHALLENGE"
                else "Advanced Difficulty"
            )

            return GeneratedQuestion(
                id=q_id,
                question=q_text,
                category="HR" if category == "HR" else "Technical",
                topic=str(data.get("topic") or decision_result.target_skill).strip(),
                difficulty=effective_difficulty,
                focus=focus_label,
                expected_aspects=[decision_result.target_concept, f"Demonstration of {effective_difficulty} principles"],
            )

        except (llm_service.LLMResponseParseError, KeyError, ValueError) as err:
            last_error = err
            if attempt < MAX_GENERATION_RETRIES:
                is_malformed_retry = True
                malformed_reason = str(err)[:120]
                continue
            raise llm_service.LLMResponseParseError(f"Failed to generate valid adaptive question: {err}") from err

    raise llm_service.LLMResponseParseError(f"Failed to generate valid adaptive question: {last_error or 'Unknown error'}")


@timed("adaptive.total")
@llm_usage.operation("adaptive_progression")
async def process_adaptive_next_question(
    request: AdaptiveNextQuestionRequest,
) -> AdaptiveNextQuestionResponse:
    """
    Main orchestration endpoint for POST /api/v1/interview/next-question.
    1. Consumes Phase 10 evaluation, previous question, answer, and interview plan/state.
    2. Runs deterministic decision engine (TARGETED_FOLLOW_UP, DEEPER_CHALLENGE, NEXT_TOPIC, RECOVERY_QUESTION, END_INTERVIEW).
    3. If END_INTERVIEW: terminates interview cleanly.
    4. If continuing: generates exactly ONE targeted question via Qwen3 with low latency.
    """
    start_time = time.perf_counter()

    plan = copy.deepcopy(request.interview_plan or {})
    state = copy.deepcopy(request.interview_state or {})
    interview_type = plan.get("interview_type")
    if interview_type not in ("Technical", "HR", "Mixed"):
        raise InterviewStateError("Saved interview type is missing or invalid. Restore the session configuration before continuing.")
    subject = plan.get("subject")
    if subject and subject not in SUBJECT_TOPICS:
        raise InterviewStateError("Unsupported saved interview subject")
    if subject and interview_type != "Technical":
        raise InterviewStateError("Saved subject conflicts with interview type. Restore the session configuration.")
    for key in ("covered_stages", "covered_topics", "covered_skills"):
        state.setdefault(key, [])
    # Unknown evaluations hold difficulty; never manufacture a passing score.
    signal = performance_level(request.evaluation)
    evaluation = request.evaluation or AdaptiveEvaluationInput()
    current_diff = state.get("current_difficulty", request.difficulty)
    if current_diff not in DIFFICULTY_LEVELS:
        current_diff = "Medium"
    interview_mode = plan.get("mode") or request.interview_mode or "STATIC"

    # Update state metrics
    questions_asked = state.get("questions_asked", len(request.question_history) or 1)
    min_q = plan.get("min_questions", MIN_DYNAMIC_QUESTIONS)
    max_q = plan.get("max_questions", MAX_DYNAMIC_QUESTIONS if interview_mode == "DYNAMIC" else 10)
    schedule = plan.get("category_schedule") or category_schedule(interview_type, max_q)
    if (len(schedule) != max_q or any(c not in ("HR", "Technical") for c in schedule)
            or (interview_type != "Mixed" and any(c != interview_type for c in schedule))
            or (interview_type == "Mixed" and abs(schedule.count("HR") - schedule.count("Technical")) > 1)):
        raise InterviewStateError("Saved category plan is invalid. Restore the session configuration.")
    plan["category_schedule"] = schedule
    covered_stages = list(state.get("covered_stages", []))
    covered_topics = list(state.get("covered_topics", []))
    covered_skills = list(state.get("covered_skills", []))

    # Score tracking
    recent_scores = list(state.get("recent_scores", []))
    if signal != "unknown":
        recent_scores.append(evaluation.score)
    state["recent_scores"] = recent_scores[-6:]

    consecutive_strong = state.get("consecutive_strong_answers", 0)
    consecutive_weak = state.get("consecutive_weak_answers", 0)
    if signal == "strong":
        consecutive_strong += 1
        consecutive_weak = 0
    elif signal == "weak":
        consecutive_weak += 1
        consecutive_strong = 0
    else:
        consecutive_strong = 0
        consecutive_weak = 0
    state["consecutive_strong_answers"] = consecutive_strong
    state["consecutive_weak_answers"] = consecutive_weak

    current_stage = state.get("current_stage", "TECHNICAL_FUNDAMENTALS")

    # 1. Deterministic Decision Layer
    decision_result = decide_next_action(
        evaluation=evaluation,
        previous_question=request.previous_question,
        category=request.category,
        difficulty=current_diff,
        relevant_skills=request.relevant_skills,
        current_topic=request.current_topic,
        consecutive_follow_ups=request.consecutive_follow_ups,
        answer_history=request.answer_history,
        question_history=request.question_history,
        candidate_answer=request.candidate_answer,
        allow_recovery=True,
        current_stage=current_stage,
        interview_mode=interview_mode,
        questions_asked=questions_asked,
        min_questions=min_q,
        max_questions=max_q,
        covered_stages=covered_stages,
        covered_topics=covered_topics,
        allow_background_follow_up=plan.get("allow_background_follow_up", False) and interview_type == "Technical",
    )

    # One-level changes based on observed correctness; two consecutive strong
    # answers are needed for promotion. Introduction does not assess technical skill.
    next_diff = current_diff
    if current_stage != "INTRO":
        index = DIFFICULTY_LEVELS.index(current_diff)
        if signal == "weak":
            next_diff = DIFFICULTY_LEVELS[max(0, index - 1)]
        elif signal == "strong" and consecutive_strong >= 2:
            next_diff = DIFFICULTY_LEVELS[min(2, index + 1)]
            state["consecutive_strong_answers"] = 0
    else:
        state["consecutive_strong_answers"] = 0
    decision_result.next_difficulty = next_diff
    if decision_result.decision != "END_INTERVIEW":
        if signal == "unknown":
            decision_result.decision = "NEXT_TOPIC"
            decision_result.is_follow_up = False
            decision_result.reason = "Evaluation unavailable; maintaining difficulty and continuing safely."
        elif signal == "weak" and current_stage != "INTRO":
            decision_result.decision = "RECOVERY_QUESTION" if request.consecutive_follow_ups < MAX_CONSECUTIVE_FOLLOWUPS else "NEXT_TOPIC"
            decision_result.is_follow_up = decision_result.decision == "RECOVERY_QUESTION"
            decision_result.reason = f"Observed difficulty with this answer; returning to fundamentals at {next_diff}."
        elif next_diff != current_diff:
            decision_result.decision = "ADVANCE_DIFFICULTY"
            decision_result.is_follow_up = False
            decision_result.reason = f"Two consecutive well-reasoned answers; progressing to {next_diff}."
        elif decision_result.decision == "ADVANCE_DIFFICULTY":
            decision_result.decision = "NEXT_TOPIC"
            decision_result.reason = "Maintaining difficulty until strong performance is sustained."

    if subject and interview_mode == "DYNAMIC" and questions_asked >= min_q and len(set(covered_topics)) >= 3 and len(recent_scores) >= 5:
        decision_result.decision = "END_INTERVIEW"
        decision_result.reason = "Sufficient observed performance across the selected subject."
        decision_result.is_follow_up = False

    # 2. Check for END_INTERVIEW
    if decision_result.decision == "END_INTERVIEW":
        elapsed_ms = round((time.perf_counter() - start_time) * 1000)
        state["last_decision"] = "END_INTERVIEW"
        return AdaptiveNextQuestionResponse(
            decision="END_INTERVIEW",
            reason=decision_result.reason,
            targetSkill=decision_result.target_skill,
            targetConcept=decision_result.target_concept,
            difficulty=decision_result.difficulty,
            nextDifficulty=decision_result.next_difficulty,
            isFollowUp=False,
            question=None,
            end_interview=True,
            conversational_lead_in="Thank you for completing the interview questions.",
            interview_plan=plan,
            interview_state=state,
            processing_time_ms=elapsed_ms,
        )

    # 3. Handle Stage Progression & Topic Selection if NEXT_TOPIC or ADVANCE_DIFFICULTY
    cand_name = plan.get("candidate_name") or ""
    projects = named_projects(plan.get("candidate_projects") or [plan.get("active_project")])
    active_project = resolve_project(projects, active_project=plan.get("active_project"))
    proj_name = active_project.get("name") if active_project else None

    target_skill = decision_result.target_skill
    target_concept = decision_result.target_concept
    next_stage = current_stage
    lead_in = decision_result.conversational_lead_in

    if decision_result.decision in ("NEXT_TOPIC", "ADVANCE_DIFFICULTY"):
        # Advance stage according to plan
        stages_planned = plan.get("stages_planned", [])
        stage_idx = plan.get("current_stage_index", 0) + 1
        while stage_idx < len(stages_planned) and stages_planned[stage_idx] in ("INTRO", "RESUME_BACKGROUND") and not plan.get("allow_background_follow_up", False):
            stage_idx += 1
        plan["current_stage_index"] = stage_idx

        if stage_idx < len(stages_planned):
            next_stage = stages_planned[stage_idx]
        else:
            next_stage = "FINAL_ADAPTIVE"
        state["current_stage"] = next_stage

        # Pick next target skill from priority list that hasn't been heavily covered
        skills_pri = plan.get("skills_priority", [])
        uncovered = [s for s in skills_pri if s not in covered_topics and s not in covered_skills]
        if uncovered:
            target_skill = uncovered[0]
        elif skills_pri:
            target_skill = skills_pri[questions_asked % len(skills_pri)]
        else:
            target_skill = "Software Engineering"

        # Determine concept based on stage
        if next_stage in ("PROJECT_INTRO", "PROJECT"):
            target_skill = proj_name or "Key Project"
            target_concept = f"overview of {target_skill} and candidate contribution"
            instruction = f"Ask candidate to walk through their project {target_skill} and explain their specific contribution."
        elif next_stage == "PROJECT_DEEP_DIVE":
            target_skill = proj_name or "Key Project"
            proj_techs = active_project.get("technologies", []) if active_project else []
            chosen_tech = proj_techs[0] if proj_techs else "architecture"
            target_concept = f"why {chosen_tech} was selected and how data or components were structured"
            instruction = f"Ask why they chose {chosen_tech} for {target_skill} and how they structured the data or service architecture."
        elif next_stage in ("ADVANCED_SCENARIO", "ADVANCED_TECHNICAL"):
            target_concept = f"scalability, performance optimization, and concurrent traffic handling for {target_skill}"
            instruction = f"Ask a production scenario on optimizing {target_skill} under heavy concurrent traffic."
        elif next_stage == "RESUME_BACKGROUND":
            target_concept = f"hands-on experience and familiarity with {target_skill}"
            instruction = f"Ask about their background and comfort level working with {target_skill}."
        else:
            target_concept = f"core mechanics and design principles of {target_skill}"
            instruction = f"Ask a clear conceptual question regarding {target_concept}."

        next_follow_ups = 0
    else:
        # Follow-up on same topic
        next_follow_ups = request.consecutive_follow_ups + 1
        instruction = f"Follow up directly on the candidate's previous response regarding {target_concept}."

    # 4. Generate the single question via Qwen3 with low latency
    effective_diff = next_diff
    if subject:
        next_stage = "TECHNICAL_FUNDAMENTALS"
        if target_skill not in SUBJECT_TOPICS[subject]:
            target_skill = SUBJECT_TOPICS[subject][questions_asked % len(SUBJECT_TOPICS[subject])]
        target_concept = target_skill
        instruction = f"Assess {target_skill} within {subject}. Use the previous answer and evaluation to choose a new assessment."
    if effective_diff != "Hard" and next_stage in ("ADVANCED_SCENARIO", "ADVANCED_TECHNICAL"):
        next_stage = "TECHNICAL_FUNDAMENTALS"
        target_concept = f"fundamentals and application of {target_skill}"
        instruction = f"Ask about {target_concept} at {effective_diff} level."
    if decision_result.decision == "RECOVERY_QUESTION":
        target_concept = f"a simpler prerequisite of {target_skill}"
    # The saved interview type, not the previous question label, controls scope.
    category = interview_type
    counts = dict(state.get("category_counts") or {})
    if interview_type == "Mixed":
        if (set(counts) != {"HR", "Technical"} or any(type(v) is not int or v < 0 for v in counts.values())
                or sum(counts.values()) != questions_asked):
            raise InterviewStateError("Saved category progress is missing. Reload the owned session before continuing.")
        category = schedule[min(questions_asked, len(schedule) - 1)]
        previous_category = request.category
        if decision_result.is_follow_up and previous_category in counts:
            other = "HR" if previous_category == "Technical" else "Technical"
            if counts[previous_category] <= counts[other]:
                category = previous_category
        # A follow-up consumes a slot in its category, never the other category's budget.
        if counts[category] >= schedule.count(category):
            category = "HR" if category == "Technical" else "Technical"
        if category != previous_category:
            decision_result.decision = "NEXT_TOPIC"
            decision_result.is_follow_up = False
            decision_result.reason = "Continuing the saved Mixed interview category distribution."
            next_follow_ups = 0
        if category == "Technical" and (category != previous_category or next_stage == "BEHAVIORAL"):
            next_stage = "TECHNICAL_FUNDAMENTALS"
            skills = plan.get("skills_priority") or ["Software Engineering"]
            target_skill = skills[counts["Technical"] % len(skills)]
            target_concept = f"fundamentals and application of {target_skill}"
            instruction = f"Ask a technical question about {target_concept}."
    if category == "HR":
        next_stage = "BEHAVIORAL"
        if decision_result.is_follow_up:
            target_skill = request.current_topic
        else:
            target_skill = next((topic for topic in HR_TOPICS if topic not in covered_topics),
                                HR_TOPICS[max(0, counts.get("HR", questions_asked) - 1) % len(HR_TOPICS)])
            if target_skill == "Project experience" and active_project:
                next_stage = "PROJECT_INTRO"
        target_concept = target_skill
        instruction = "Ask about personal actions, interpersonal decisions and outcomes."
    state["interview_type"] = interview_type
    state["current_stage"] = next_stage
    state["current_topic"] = target_skill
    state["current_difficulty"] = effective_diff
    state["subject"] = subject
    q_num = questions_asked + 1

    # Ground the follow-up in the immediate conversation, not the first resume project.
    project_context = None
    if not subject:
        if decision_result.is_follow_up:
            project_context = resolve_project(projects, topic=request.current_topic,
                previous_question=request.previous_question, candidate_answer=request.candidate_answer,
                follow_up=True)
        elif "PROJECT" in next_stage:
            project_context = active_project
        elif category == "HR":
            project_context = resolve_project(projects, previous_question=request.previous_question,
                                              candidate_answer=request.candidate_answer, follow_up=True)
    if project_context:
        plan["active_project"] = project_context
        if category != "HR" and "PROJECT" in next_stage:
            target_skill = project_context["name"]
            state["current_topic"] = target_skill

    try:
        gen_q, gen_lead_in = await generate_single_next_question(
            decision=decision_result.decision,
            stage=next_stage,
            target_skill=target_skill,
            target_concept=target_concept,
            difficulty=effective_diff,
            category=category,
            role=request.role,
            previous_question=request.previous_question,
            candidate_answer=request.candidate_answer,
            candidate_name=cand_name,
            project_name=project_context["name"] if project_context else None,
            project_context=project_context,
            conversational_instruction=instruction,
            question_history=request.question_history,
            q_index=q_num,
            subject=subject,
            evaluation=request.evaluation,
            answer_history=request.answer_history,
            allow_opening=bool(plan.get("allow_background_follow_up")) and not subject and interview_type == "Technical",
        )
    except LLMResponseParseError:
        if category == "HR":
            raise
        logger.warning("generate_single_next_question exhausted retries; using deterministic fallback")
        gen_q = generate_fallback_question(
            decision=decision_result.decision,
            target_skill=target_skill,
            target_concept=target_concept,
            difficulty=effective_diff,
            category=category,
            subject=subject,
            history=request.question_history,
        )
        gen_q.id = f"q{q_num}"
        gen_lead_in = decision_result.conversational_lead_in or ""

    if category == "HR":
        target_skill = target_concept = gen_q.topic
        state["current_topic"] = target_skill
        if decision_result.is_follow_up and not gen_q.is_follow_up:
            decision_result.decision = "NEXT_TOPIC"
            decision_result.is_follow_up = False
            decision_result.reason = "Distinct follow-ups were exhausted for the preceding example."
            lead_in = "Let's move to another topic."
            next_follow_ups = 0
            plan["current_stage_index"] = plan.get("current_stage_index", 0) + 1
            next_stage = state["current_stage"] = "BEHAVIORAL"
    if not decision_result.is_follow_up:
        state["covered_stages"].append(next_stage)
        state["covered_topics"].append(target_skill)
        state["covered_skills"].append(target_skill)

    state["questions_asked"] = q_num
    counts[category] = counts.get(category, 0) + 1
    state["category_counts"] = counts
    state["consecutive_follow_ups"] = next_follow_ups
    state["last_decision"] = decision_result.decision
    if gen_lead_in:
        lead_in = gen_lead_in

    elapsed_ms = round((time.perf_counter() - start_time) * 1000)

    return AdaptiveNextQuestionResponse(
        decision=decision_result.decision,
        reason=decision_result.reason,
        targetSkill=target_skill,
        targetConcept=target_concept,
        difficulty=decision_result.difficulty,
        nextDifficulty=decision_result.next_difficulty,
        isFollowUp=decision_result.is_follow_up,
        question=gen_q,
        end_interview=False,
        conversational_lead_in=lead_in,
        interview_plan=plan,
        interview_state=state,
        processing_time_ms=elapsed_ms,
    )
