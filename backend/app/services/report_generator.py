"""
Final Performance Report Generation Engine — Phase 14

Transforms persisted interview data (questions, candidate answers, evaluations,
adaptive history) into a comprehensive, professional, viva-ready final performance report.

Authoritative Principles:
  1. Real Data Only: Strictly derived from evaluated answers and session history.
     NO mock data, NO random scores, NO fabricated candidate performance.
  2. Deterministic Score Aggregation: Average saved answer scores without regrading.
     Keep the rubric metadata with new reports and preserve existing scores.
  3. Question Breakdown: Preserves question, category, topic, difficulty, candidate answer,
     all 4 dimension scores, overall score, strengths, improvements, and follow-up status.
     Excludes internal debug, raw prompts, and model chain-of-thought.
  4. Skill / Topic Performance: Computed ONLY for assessed skills.
  5. Strengths & Weaknesses: Deterministically aggregated from evaluations, deduplicated.
  6. Actionable Recommendations: Concrete, prioritized study & interview prep advice
     traceable to actual assessed weak areas.
  7. Adaptive Summary: Summarizes progression, follow-ups, and adaptability.
"""

from typing import Any, Dict, List, Optional, Tuple
from app.schemas.evaluation import CONCEPTUAL_RUBRIC, MIXED_RUBRICS
from app.services.reference_answer import clean_reference


def calculate_grade(overall_score: int) -> Tuple[str, str]:
    """
    Map deterministic 0-100 overall score to standard academic grade and label.
    """
    score = max(0, min(100, int(round(overall_score))))
    if score >= 90:
        return "A+", "Outstanding Performance"
    if score >= 80:
        return "A", "Strong Performance"
    if score >= 70:
        return "B", "Proficient Performance"
    if score >= 60:
        return "C", "Developing Performance"
    if score >= 50:
        return "D", "Needs Improvement"
    return "F", "Unsatisfactory Performance"


def _clamp_score(val: Any, default: int = 0) -> int:
    """Safely clamp a numeric value to [0, 100]."""
    try:
        if val is None:
            return default
        num = float(val)
        return max(0, min(100, int(round(num))))
    except (ValueError, TypeError):
        return default


def evaluation_available(answer):
    ev = answer.get("evaluation") or answer
    score = answer.get("score") if answer.get("score") is not None else ev.get("score")
    return (ev.get("answer_status") not in ("ERROR", "FAILED", "UNAVAILABLE")
            and ev.get("evaluation_status") not in ("ERROR", "FAILED", "UNAVAILABLE")
            and isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 100)


def aggregate_scores(
    answers: List[Dict[str, Any]],
    total_planned_questions: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Deterministic score aggregation across all interview answers.
    Handles:
      - zero evaluated questions
      - skipped questions (score = 0)
      - incomplete sessions
      - missing dimensions / malformed scores
      - bounds all values to [0, 100]
    """
    answers = [a for a in answers if a.get("skipped") or evaluation_available(a)]
    if not answers:
        return {
            "overall": 0,
            "grade": "F",
            "grade_label": "No Questions Evaluated",
            "technical_accuracy": 0,
            "relevance": 0,
            "depth": 0,
            "clarity": 0,
            "questions_evaluated": 0,
            "questions_skipped": 0,
            # UI / backward-compatibility aliases
            "technicalKnowledge": 0,
            "problemSolving": 0,
            "communication": 0,
            "jobRelevance": 0,
            "confidence": 0,
        }

    total_presented = len(answers)
    valid_answers = [a for a in answers if not a.get("skipped")]
    skipped_count = total_presented - len(valid_answers)

    # 1. Overall Score: average of all presented questions (skipped questions count as 0)
    all_scores = []
    for a in answers:
        if a.get("skipped"):
            all_scores.append(0)
        else:
            eval_data = a.get("evaluation") or {}
            sc = a.get("score") if a.get("score") is not None else eval_data.get("score")
            all_scores.append(_clamp_score(sc, 0))

    overall_score = round(sum(all_scores) / total_presented) if total_presented > 0 else 0
    overall_score = max(0, min(100, overall_score))

    # 2. Dimensions: averaged across valid evaluated answers (or 0 if all skipped)
    if valid_answers:
        tech_scores = []
        rel_scores = []
        depth_scores = []
        clarity_scores = []

        for a in valid_answers:
            ev = a.get("evaluation") or a
            tech_scores.append(_clamp_score(ev.get("technical_accuracy") if ev.get("technical_accuracy") is not None else ev.get("technicalAccuracy"), 0))
            rel_scores.append(_clamp_score(ev.get("relevance"), 0))
            depth_scores.append(_clamp_score(ev.get("depth"), 0))
            clarity_scores.append(_clamp_score(ev.get("clarity"), 0))

        avg_tech = round(sum(tech_scores) / len(tech_scores))
        avg_rel = round(sum(rel_scores) / len(rel_scores))
        avg_depth = round(sum(depth_scores) / len(depth_scores))
        avg_clarity = round(sum(clarity_scores) / len(clarity_scores))
    else:
        avg_tech = 0
        avg_rel = 0
        avg_depth = 0
        avg_clarity = 0

    grade, grade_label = calculate_grade(overall_score)

    return {
        "overall": overall_score,
        "grade": grade,
        "grade_label": grade_label,
        "technical_accuracy": avg_tech,
        "relevance": avg_rel,
        "depth": avg_depth,
        "clarity": avg_clarity,
        "questions_evaluated": len(valid_answers),
        "questions_skipped": skipped_count,
        # Backward-compatibility aliases for dashboard/existing UI
        "technicalKnowledge": avg_tech,
        "problemSolving": avg_depth,
        "communication": avg_clarity,
        "jobRelevance": avg_rel,
        "confidence": None,
    }


def build_question_breakdown(
    questions: List[Dict[str, Any]],
    answers: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Constructs clean, candidate-facing question-by-question breakdown.
    Excludes internal debugging, raw model prompts, and model chain-of-thought.
    """
    q_map: Dict[str, Dict[str, Any]] = {}
    for idx, q in enumerate(questions):
        qid = str(q.get("id") or q.get("question_id") or f"q{idx + 1}")
        q_map[qid] = {**q, "_order": idx + 1}

    breakdown = []
    for idx, a in enumerate(answers):
        qid = str(a.get("questionId") or a.get("question_id") or f"q{idx + 1}")
        q_meta = q_map.get(qid, {})

        q_text = (
            a.get("question")
            or q_meta.get("question")
            or q_meta.get("question_text")
            or f"Question {idx + 1}"
        )
        category = a.get("category") or q_meta.get("category") or "Technical"
        topic = a.get("topic") or q_meta.get("topic") or "General"
        difficulty = a.get("difficulty") or q_meta.get("difficulty") or "Medium"
        stage = q_meta.get("stage") or "TECHNICAL_FUNDAMENTALS"
        focus = q_meta.get("focus") or topic
        is_follow_up = bool(q_meta.get("is_follow_up") or a.get("is_follow_up", False))

        is_skipped = bool(a.get("skipped", False))
        is_timed_out = bool(a.get("timedOut") or a.get("timed_out", False))
        time_spent = int(a.get("timeSpent") or a.get("time_spent_secs") or 0)
        candidate_ans = a.get("answer") or a.get("answer_text") or ""

        ev = {**(a.get("feedback") or {}), **(a.get("evaluation") or a)}
        if is_skipped:
            score = 0
            tech = 0
            rel = 0
            depth = 0
            clarity = 0
            answer_status = "SKIPPED"
            strengths = []
            improvements = ["Question was skipped. Practice answering this topic under interview conditions."]
            suggested_ans = ev.get("suggested_answer") or ev.get("suggestedAnswer") or ""
        else:
            score = _clamp_score(a.get("score") if a.get("score") is not None else ev.get("score"), 0)
            tech = _clamp_score(ev.get("technical_accuracy") if ev.get("technical_accuracy") is not None else ev.get("technicalAccuracy"), 0)
            rel = _clamp_score(ev.get("relevance"), 0)
            depth = _clamp_score(ev.get("depth"), 0)
            clarity = _clamp_score(ev.get("clarity"), 0)
            answer_status = ev.get("answer_status") or ("CORRECT" if score >= 75 else "PARTIAL" if score >= 40 else "INCORRECT")

            raw_str = ev.get("strengths") or []
            strengths = [str(s).strip() for s in raw_str if str(s).strip() and not str(s).startswith("Internal")]
            raw_imp = ev.get("improvements") or []
            improvements = [str(i).strip() for i in raw_imp if str(i).strip() and not str(i).startswith("Internal")]
            suggested_ans = ev.get("suggested_answer") or ev.get("suggestedAnswer") or ""

        available = is_skipped or evaluation_available(a)
        if not available:
            score = tech = rel = depth = clarity = None
            answer_status = "UNAVAILABLE"
            strengths = improvements = []
        suggested_ans = clean_reference(suggested_ans, q_text, candidate_ans)
        breakdown.append({
            "evaluation_status": "COMPLETED" if available else "UNAVAILABLE",
            "question_order": idx + 1,
            "question_id": qid,
            "question": q_text,
            "category": category,
            "topic": topic,
            "difficulty": difficulty,
            "stage": stage,
            "focus": focus,
            "is_follow_up": is_follow_up,
            "candidate_answer": candidate_ans,
            "skipped": is_skipped,
            "timed_out": is_timed_out,
            "time_spent_secs": time_spent,
            "score": score,
            "rubric_version": ev.get("rubric_version"),
            "technical_accuracy": tech,
            "relevance": rel,
            "depth": depth,
            "clarity": clarity,
            "answer_status": answer_status,
            "strengths": strengths,
            "improvements": improvements,
            "suggested_answer": suggested_ans,
        })

    return breakdown


def analyze_topic_performance(question_breakdown: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Computes performance by skill/topic for ASSESSED topics only.
    Never infers skills that were not tested.
    """
    if not question_breakdown:
        return []

    topic_groups: Dict[str, List[Dict[str, Any]]] = {}
    for q in question_breakdown:
        if q.get("evaluation_status") == "UNAVAILABLE" or q.get("score") is None:
            continue
        t = q.get("topic") or "General"
        # Normalize general case
        norm_t = t.strip().title() if t.lower() not in ("sql", "api", "rest", "dsa", "oop") else t.strip().upper()
        if norm_t not in topic_groups:
            topic_groups[norm_t] = []
        topic_groups[norm_t].append(q)

    results = []
    for topic_name, q_list in topic_groups.items():
        q_count = len(q_list)
        valid_scores = [q["score"] for q in q_list]
        avg_score = round(sum(valid_scores) / q_count) if q_count > 0 else 0

        if avg_score >= 80:
            proficiency = "Strong"
        elif avg_score >= 65:
            proficiency = "Proficient"
        else:
            proficiency = "Needs Practice"

        # Collect primary category
        categories = [q.get("category", "Technical") for q in q_list]
        primary_cat = max(set(categories), key=categories.count) if categories else "Technical"

        results.append({
            "topic": topic_name,
            "category": primary_cat,
            "question_count": q_count,
            "average_score": avg_score,
            "proficiency": proficiency,
        })

    # Sort topics by average score descending, then question count descending
    results.sort(key=lambda x: (x["average_score"], x["question_count"]), reverse=True)
    return results


def analyze_strengths_and_weaknesses(
    question_breakdown: List[Dict[str, Any]],
    dimension_scores: Dict[str, Any],
) -> Tuple[List[str], List[str]]:
    """
    Deterministic synthesis of candidate strengths and weaknesses.
    Deduplicates repeated statements and correlates with dimensional metrics.
    """
    if not question_breakdown:
        return [], []

    strengths: List[str] = []
    weaknesses: List[str] = []
    seen_s = set()
    seen_w = set()

    def add_strength(s: str):
        clean = s.strip()
        lower = clean.lower()
        if clean and lower not in seen_s:
            seen_s.add(lower)
            strengths.append(clean)

    def add_weakness(w: str):
        clean = w.strip()
        lower = clean.lower()
        if clean and lower not in seen_w:
            seen_w.add(lower)
            weaknesses.append(clean)

    # 1. Macro dimension strengths
    tech = dimension_scores.get("technical_accuracy", 0)
    rel = dimension_scores.get("relevance", 0)
    depth = dimension_scores.get("depth", 0)
    clarity = dimension_scores.get("clarity", 0)

    if tech >= 80:
        add_strength("Consistently demonstrates high technical accuracy across core concepts")
    if rel >= 85:
        add_strength("Answers remain tightly focused and directly relevant to interview prompts")
    legacy = dimension_scores.get("rubric_version") not in (CONCEPTUAL_RUBRIC, MIXED_RUBRICS)
    if legacy and depth >= 80:
        add_strength("Provides thorough, deep explanations covering underlying principles")
    if clarity >= 80:
        add_strength("Articulates thoughts with clear structure and professional communication")

    # 2. Macro dimension weaknesses
    if tech < 60 and tech > 0:
        add_weakness("Technical accuracy needs reinforcement on fundamental terminology and mechanisms")
    if legacy and 0 < depth < 60:
        add_weakness("Explanations tend to be high-level; provide deeper trade-off and edge-case analysis")
    if rel < 65 and rel > 0:
        add_weakness("Responses occasionally wander off-topic; address the primary question directly")
    if clarity < 60 and clarity > 0:
        add_weakness("Communication clarity can be improved by structuring answers logically upfront")

    # 3. Micro per-question feedback aggregation
    for q in question_breakdown:
        if q.get("evaluation_status") == "UNAVAILABLE" or q.get("score") is None:
            continue
        if q.get("skipped"):
            add_weakness(f"Skipped question on {q.get('topic', 'topic')} (Question #{q.get('question_order')})")
            continue

        # For high-scoring questions, extract strengths
        if q.get("strengths"):
            for s in q.get("strengths") or []:
                if len(s) > 10:
                    add_strength(s)
        # For low-scoring questions, extract improvement areas
        suggestions_only = q.get("rubric_version") == CONCEPTUAL_RUBRIC and q.get("answer_status") == "CORRECT"
        if q.get("improvements") and not suggestions_only:
            for imp in q.get("improvements") or []:
                if len(imp) > 10:
                    add_weakness(imp)

    return strengths[:6], weaknesses[:6]


def build_adaptive_summary(
    interview_plan: Optional[Dict[str, Any]],
    interview_state: Optional[Dict[str, Any]],
    question_breakdown: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Generates a candidate-friendly summary of the adaptive interview progression.
    Uses readable language without raw internal enum identifiers.
    """
    total_q = len(question_breakdown)
    follow_up_questions = [q for q in question_breakdown if q.get("is_follow_up")]
    follow_up_count = len(follow_up_questions)
    follow_up_topics = list({q.get("topic", "General") for q in follow_up_questions})

    difficulties = [q.get("difficulty", "Medium") for q in question_breakdown]
    has_hard = "Hard" in difficulties
    has_easy = "Easy" in difficulties

    changes = [level for i, level in enumerate(difficulties) if i == 0 or level != difficulties[i - 1]]
    progression = " → ".join(changes) if changes else "No questions assessed"
    summary_text = f"Assessed {total_q} questions, including {follow_up_count} follow-up questions."
    adaptability_rating = "Follow-up assessment" if follow_up_count else "Direct assessment"

    return {
        "total_follow_ups": follow_up_count,
        "follow_up_topics": follow_up_topics,
        "difficulty_progression": progression,
        "adaptability_rating": adaptability_rating,
        "summary_text": summary_text,
    }


def generate_recommendations(
    topic_performance: List[Dict[str, Any]],
    weaknesses: List[str],
    dimension_scores: Dict[str, Any],
) -> List[str]:
    """
    Deterministic preparation recommendations strictly tied to observed weak areas.
    """
    recs: List[str] = []
    seen = set()

    def add_rec(r: str):
        clean = r.strip()
        lower = clean.lower()
        if clean and lower not in seen:
            seen.add(lower)
            recs.append(clean)

    legacy = dimension_scores.get("rubric_version") not in (CONCEPTUAL_RUBRIC, MIXED_RUBRICS)
    # 1. Recommendations from low-scoring topics
    weak_topics = [t for t in topic_performance if t.get("average_score", 100) < 70]
    for wt in weak_topics:
        topic_name = wt.get("topic", "Core Subject")
        score = wt.get("average_score", 0)
        if score == 0:
            add_rec(f"Prioritize foundational study of {topic_name} — practice core concepts and implement working examples.")
        elif score < 50:
            add_rec(f"Strengthen understanding of {topic_name} — review standard patterns and common interview problem scenarios.")
        elif legacy:
            add_rec(f"Refine technical depth in {topic_name} — focus on performance trade-offs, internal mechanics, and edge cases.")
        else:
            add_rec(f"Practice explaining the essential concepts in {topic_name} and addressing each part of the question.")

    # 2. Recommendations from dimensional metrics
    tech = dimension_scores.get("technical_accuracy", 0)
    depth = dimension_scores.get("depth", 0)
    clarity = dimension_scores.get("clarity", 0)
    relevance = dimension_scores.get("relevance", 0)

    if legacy and 0 < depth < 65:
        add_rec("When answering technical questions, proactively discuss time/space complexity and alternative architectural approaches.")
    if clarity < 65 and clarity > 0:
        add_rec("Practice structuring technical answers aloud — begin with a direct 1-sentence definition before detailing implementation details.")
    if tech < 65 and tech > 0:
        add_rec("Review precision in technical terminology to eliminate ambiguities in architectural explanations.")
    if relevance < 70 and relevance > 0:
        add_rec("Listen carefully to the exact prompt constraints before answering to ensure 100% focused coverage.")

    # 3. Recommendations from specific weakness items
    for w in weaknesses:
        if "skipped" in w.lower():
            continue
        if len(w) > 15:
            # Format as actionable advice
            if not w.lower().startswith("practice") and not w.lower().startswith("review") and not w.lower().startswith("study"):
                add_rec(f"Address specific feedback: {w}")
            else:
                add_rec(w)


    return recs[:5]


def generate_final_report(
    session_id: str,
    role: str,
    interview_type: str,
    difficulty: str,
    questions: List[Dict[str, Any]],
    answers: List[Dict[str, Any]],
    duration_secs: int = 0,
    interview_plan: Optional[Dict[str, Any]] = None,
    interview_state: Optional[Dict[str, Any]] = None,
    total_planned_questions: Optional[int] = None,
    rubric_version: str | None = None,
) -> Dict[str, Any]:
    """
    Primary report generation entrypoint.
    Compiles full, authoritative, viva-ready performance report payload.
    """
    # 1. Deterministic score aggregation
    scores_data = aggregate_scores(answers, total_planned_questions)
    overall_score = scores_data["overall"]
    grade = scores_data["grade"]
    grade_label = scores_data["grade_label"]

    # 2. Detailed question-by-question breakdown
    breakdown = build_question_breakdown(questions, answers)
    rubrics = {row["rubric_version"] for row in breakdown if not row["skipped"] and evaluation_available(row)}
    if CONCEPTUAL_RUBRIC in rubrics:
        rubric_version = MIXED_RUBRICS if len(rubrics) > 1 else CONCEPTUAL_RUBRIC
    if rubric_version in (CONCEPTUAL_RUBRIC, MIXED_RUBRICS):
        scores_data["rubric_version"] = rubric_version

    # 3. Topic performance analysis (assessed only)
    topic_perf = analyze_topic_performance(breakdown)

    # 4. Deterministic strengths & weaknesses
    strengths, weaknesses = analyze_strengths_and_weaknesses(breakdown, scores_data)

    # 5. Adaptive progression summary
    adaptive_summary = build_adaptive_summary(interview_plan, interview_state, breakdown)

    # 6. Actionable recommendations
    recommendations = generate_recommendations(topic_perf, weaknesses, scores_data)

    total_q = total_planned_questions or max(len(questions), len(answers))
    questions_answered = len([a for a in answers if not a.get("skipped") and evaluation_available(a)])

    # 7. Embed rich structured data into scores JSON
    enriched_scores = {
        **scores_data,
        "subject": (interview_plan or {}).get("subject"),
        "grade": grade,
        "grade_label": grade_label,
        "skill_analysis": topic_perf,
        "adaptive_summary": adaptive_summary,
    }

    report = {
        "session_id": session_id,
        "subject": (interview_plan or {}).get("subject"),
        "overall_score": overall_score,
        "grade": grade,
        "grade_label": grade_label,
        "role": role or "Software Engineer",
        "interview_type": interview_type or "Technical",
        "difficulty": difficulty or "Medium",
        "questions_answered": questions_answered,
        "total_questions": total_q,
        "duration_secs": max(0, int(duration_secs)),
        "scores": enriched_scores,
        "strengths": strengths,
        "skill_gaps": weaknesses,
        "recommendations": recommendations,
        "question_analysis": breakdown,
        "skill_analysis": topic_perf,
        "adaptive_summary": adaptive_summary,
    }

    return report


def normalize_report_for_response(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes a report record retrieved from public.interview_reports
    into a complete, fully-hydrated performance report dictionary for API responses.
    Guarantees no missing fields, consistent naming, and full backwards compatibility.
    """
    if not report:
        return {}

    overall_score = _clamp_score(report.get("overall_score"), 0)
    raw_scores = report.get("scores") if isinstance(report.get("scores"), dict) else {}

    grade = raw_scores.get("grade")
    grade_label = raw_scores.get("grade_label")
    if not grade:
        grade, grade_label = calculate_grade(overall_score)

    def dimension(*keys):
        value = next((raw_scores[k] for k in keys if raw_scores.get(k) is not None), None)
        return _clamp_score(value, 0) if value is not None else None

    tech_acc = dimension("technical_accuracy", "technicalKnowledge", "technicalAccuracy")
    rel = dimension("relevance", "jobRelevance", "experienceMatch")
    depth = dimension("depth", "problemSolving")
    clarity = dimension("clarity", "communication")

    dimensions = {
        "technical_accuracy": tech_acc,
        "relevance": rel,
        "clarity": clarity,
    }
    if raw_scores.get("rubric_version") not in (CONCEPTUAL_RUBRIC, MIXED_RUBRICS):
        dimensions["depth"] = depth

    # Extract or build question analysis
    raw_qa = report.get("question_analysis")
    question_analysis = []
    for row in raw_qa if isinstance(raw_qa, list) else []:
        # Sanitize the response only; never rewrite previously saved reports.
        normalized = dict(row)
        normalized["suggested_answer"] = clean_reference(
            row.get("suggested_answer") or row.get("suggestedAnswer"),
            row.get("question", ""), row.get("candidate_answer") or row.get("candidateAnswer", ""))
        normalized.pop("suggestedAnswer", None)
        if not row.get("skipped") and not evaluation_available(row):
            normalized.update(evaluation_status="UNAVAILABLE", score=None, technical_accuracy=None,
                              relevance=None, depth=None, clarity=None, strengths=[], improvements=[])
        question_analysis.append(normalized)

    # Extract or compute skill/topic analysis
    skill_analysis = raw_scores.get("skill_analysis")
    if not skill_analysis or not isinstance(skill_analysis, list):
        if question_analysis:
            skill_analysis = analyze_topic_performance(question_analysis)
        else:
            skill_analysis = []

    # Extract or compute adaptive summary
    adaptive_summary = raw_scores.get("adaptive_summary")
    if not adaptive_summary or not isinstance(adaptive_summary, dict):
        adaptive_summary = build_adaptive_summary(None, None, question_analysis)

    strengths = report.get("strengths") if isinstance(report.get("strengths"), list) else []
    skill_gaps = report.get("skill_gaps") if isinstance(report.get("skill_gaps"), list) else []
    recommendations = report.get("recommendations") if isinstance(report.get("recommendations"), list) else []

    # Hydrated scores object with both new and backwards-compatible keys
    hydrated_scores = {
        **raw_scores,
        "overall": overall_score,
        "grade": grade,
        "grade_label": grade_label,
        "technical_accuracy": tech_acc,
        "relevance": rel,
        "depth": depth,
        "clarity": clarity,
        "technicalKnowledge": tech_acc,
        "problemSolving": depth,
        "communication": clarity,
        "jobRelevance": rel,
        "confidence": raw_scores.get("confidence"),
        "skill_analysis": skill_analysis,
        "adaptive_summary": adaptive_summary,
    }

    return {
        "subject": raw_scores.get("subject"),
        "id": report.get("id"),
        "session_id": report.get("session_id"),
        "user_id": report.get("user_id"),
        "role": report.get("role") or "Software Engineer",
        "interview_type": report.get("interview_type") or "Technical",
        "difficulty": report.get("difficulty") or "Medium",
        "overall_score": overall_score,
        "grade": grade,
        "grade_label": grade_label,
        "questions_answered": int(report.get("questions_answered") or 0),
        "total_questions": int(report.get("total_questions") or 0),
        "duration_secs": int(report.get("duration_secs") or 0),
        "dimensions": dimensions,
        "scores": hydrated_scores,
        "strengths": strengths,
        "skill_gaps": skill_gaps,
        "weaknesses": skill_gaps,
        "recommendations": recommendations,
        "question_analysis": question_analysis,
        "skill_analysis": skill_analysis,
        "adaptive_summary": adaptive_summary,
        "created_at": report.get("created_at"),
    }

