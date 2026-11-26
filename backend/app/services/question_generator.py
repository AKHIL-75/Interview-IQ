"""
Question Generator Service — Personalized Interview Question Generation via Qwen3.

Builds personalized interview questions using candidate resume profile,
job description requirements, semantic match/gap analysis, and interview configs.
Enforces realistic interview flow:
    Stage 1: INTRO (Always Question 1 — background walkthrough)
    Stage 2: RESUME_JD (Skills and role alignment)
    Stage 3: TECHNICAL_FUNDAMENTALS (Core mechanics before projects)
    Stage 4: PROJECT (Natural project exploration: overview -> role -> architecture -> tech choices)
    Stage 5: ADVANCED_TECHNICAL (Scalability, system scenarios, trade-offs)
"""
from app.services import llm_usage


import difflib
import re
import time
from typing import Any

from app.core.config import settings
from app.prompts.question_prompts import (
    build_question_generation_prompt,
    extract_allowed_technologies,
)
from app.schemas.analysis import MatchAnalysisResponse
from app.schemas.interview import (
    GeneratedQuestion,
    InterviewStage,
    QuestionGenerationRequest,
    QuestionGenerationResponse,
)
from app.schemas.job import JobProfile
from app.schemas.resume import CandidateProfile
from app.services import llm_service
from app.services.question_policy import is_opening
from app.services.project_context import named_projects, resolve_project, explicit_project_question


# ---------------------------------------------------------------------------
# Common Hallucination Catalog
# ---------------------------------------------------------------------------
KNOWN_DISTINCT_TECH_KEYWORDS = {
    "docker", "kubernetes", "k8s", "aws", "azure", "gcp", "google cloud",
    "react", "angular", "vue", "nextjs", "next.js", "django", "flask",
    "spring boot", "spring", "kafka", "rabbitmq", "redis", "graphql",
    "flutter", "react native", "swift", "kotlin", "ruby", "rails",
    "rust", "golang", "go", "php", "laravel", "c#", ".net", "asp.net",
    "terraform", "ansible", "jenkins", "gitlab ci", "github actions",
    "mongodb", "cassandra", "dynamodb", "elasticsearch", "solr",
}


def is_technology_hallucinated(text: str, allowed_techs: list[str]) -> bool:
    """
    Check if the text introduces a specific concrete technology that is
    NOT present in the allowed technologies whitelist.
    """
    allowed_lower = {t.strip().lower() for t in allowed_techs if t.strip()}
    text_lower = text.lower()

    for tech in KNOWN_DISTINCT_TECH_KEYWORDS:
        if any(tech == a or tech in a or (len(a) > 2 and a in tech) for a in allowed_lower):
            continue

        pattern = rf"\b{re.escape(tech)}\b"
        if re.search(pattern, text_lower):
            return True

    return False


STOP_WORDS = {
    "how", "does", "in", "explain", "what", "is", "tell", "me", "about",
    "can", "you", "why", "the", "a", "an", "of", "to", "and", "for",
    "with", "your", "would", "do", "describe", "discuss"
}


def _meaningful_tokens(text: str) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    tokens = set()
    for w in words:
        if w not in STOP_WORDS and len(w) > 2:
            stemmed = re.sub(r"(?:ing|ed|es|s)$", "", w)
            tokens.add(stemmed or w)
    return tokens


def is_near_duplicate(q1: str, q2: str, threshold: float = 0.75) -> bool:
    """
    Check if two question strings are exact or near-duplicates based on
    difflib character sequence similarity and meaningful token overlap.
    """
    s1 = q1.strip().lower()
    s2 = q2.strip().lower()
    if s1 == s2:
        return True

    ratio = difflib.SequenceMatcher(None, s1, s2).ratio()
    if ratio >= threshold:
        return True

    tok1 = _meaningful_tokens(s1)
    tok2 = _meaningful_tokens(s2)
    if tok1 and tok2:
        overlap = len(tok1 & tok2) / len(tok1 | tok2)
        if overlap >= 0.70:
            return True

    return False


# ---------------------------------------------------------------------------
# Stage Sequencing & Classification Helpers
# ---------------------------------------------------------------------------
def determine_stage_sequence(question_count: int, interview_type: str = "Technical") -> list[InterviewStage]:
    """
    Produce the deterministic stage sequence for N questions.
    Guarantees:
    - Slot 1 is ALWAYS 'INTRO'.
    - Fundamentals precede Project.
    - Advanced technical topics appear toward the end.
    """
    bounded = max(1, min(20, question_count))
    if bounded == 1:
        return ["INTRO"]

    if interview_type == "HR":
        seq: list[InterviewStage] = ["INTRO"]
        while len(seq) < bounded:
            seq.append("RESUME_JD")
        return seq

    if bounded <= 5:
        base: list[InterviewStage] = ["INTRO", "RESUME_JD", "TECHNICAL_FUNDAMENTALS", "PROJECT", "ADVANCED_TECHNICAL"]
        return base[:bounded]

    if bounded <= 10:
        base = [
            "INTRO",
            "RESUME_JD",
            "RESUME_JD",
            "TECHNICAL_FUNDAMENTALS",
            "TECHNICAL_FUNDAMENTALS",
            "PROJECT",
            "PROJECT",
            "PROJECT",
            "ADVANCED_TECHNICAL",
            "ADVANCED_TECHNICAL",
        ]
        return base[:bounded]

    # 11 to 20 questions
    base = [
        "INTRO",
        "RESUME_JD",
        "RESUME_JD",
        "TECHNICAL_FUNDAMENTALS",
        "TECHNICAL_FUNDAMENTALS",
        "TECHNICAL_FUNDAMENTALS",
        "PROJECT",
        "PROJECT",
        "PROJECT",
        "PROJECT",
        "ADVANCED_TECHNICAL",
        "ADVANCED_TECHNICAL",
        "ADVANCED_TECHNICAL",
        "RESUME_JD",
        "ADVANCED_TECHNICAL",
        "TECHNICAL_FUNDAMENTALS",
        "PROJECT",
        "ADVANCED_TECHNICAL",
        "RESUME_JD",
        "ADVANCED_TECHNICAL",
    ]
    return base[:bounded]


def is_introductory_question(q_text: str) -> bool:
    """Checks if a question text is an introductory/background question."""
    t = q_text.lower()
    signals = [
        "introduce yourself",
        "walk me through your background",
        "tell me about yourself",
        "briefly introduce",
        "your background",
        "your journey",
        "overview of your experience",
        "walk through your resume",
        "candidate introduction",
    ]
    return is_opening(q_text) or any(sig in t for sig in signals)


def is_project_question(q_text: str, candidate_profile: CandidateProfile) -> bool:
    """Checks if a question asks specifically about a candidate project."""
    t = q_text.lower()
    for p in candidate_profile.key_projects:
        if p.name.lower() in t:
            return True
    return "in your project" in t or "walk me through a project" in t


def is_advanced_question(q_text: str) -> bool:
    """Checks if a question addresses advanced scalability, concurrency, or system design."""
    t = q_text.lower()
    signals = [
        "scalab", "scale", "concurrency", "high traffic", "millions of",
        "latency", "caching", "rate limit", "load balanc", "system design",
        "distributed", "bottleneck", "trade-off"
    ]
    return any(sig in t for sig in signals)


def generate_fallback_question(
    index: int,
    candidate_profile: CandidateProfile,
    job_profile: JobProfile,
    analysis: MatchAnalysisResponse | None,
    interview_type: str,
    difficulty: str,
    used_topics: set[str],
    stage: InterviewStage = "TECHNICAL_FUNDAMENTALS",
) -> GeneratedQuestion:
    """
    Deterministic question generator strictly calibrated to the requested stage.
    """
    qid = f"q{index + 1}"
    if interview_type != "Technical":
        raise llm_service.LLMResponseParseError("No generic fallback is permitted for HR or Mixed interviews. Please retry.")
    name_str = f"Hi {candidate_profile.candidate_name}, " if candidate_profile.candidate_name else "Hi, "

    if stage == "INTRO" or index == 0:
        return GeneratedQuestion(
            id=qid,
            question=f"{name_str}could you please introduce yourself and briefly walk me through your background?",
            category="Technical",
            topic="Candidate Introduction",
            difficulty="Easy",
            stage="INTRO",
            focus="Introduction",
            expected_aspects=[
                "Structured overview of education and professional background",
                "Summary of core technical competencies and areas of interest",
            ],
        )

    if stage == "RESUME_JD":
        cand_skills = candidate_profile.extracted_skills or ["Software Engineering"]
        target_skill = cand_skills[(index - 1) % len(cand_skills)]
        return GeneratedQuestion(
            id=qid,
            question=f"I see that {target_skill} is one of your key skills. How have you applied {target_skill} in your projects to build reliable software?",
            category="Technical",
            topic=target_skill,
            difficulty=difficulty,
            stage="RESUME_JD",
            focus="Matched Skill",
            expected_aspects=[f"Practical application of {target_skill}", "Clear understanding of core principles"],
        )

    if stage == "PROJECT":
        projects = named_projects(candidate_profile.key_projects)
        if projects:
            proj = projects[0]
            proj_name = proj["name"]
            if (index % 2 == 0):
                q_text = f"I see that you worked on {proj_name}. Could you walk me through the project, explain what problem it solves, and describe your core contribution?"
            else:
                q_text = f"For your {proj_name} project, can you explain how you structured the components and the trade-offs behind that design?"
        else:
            q_text = "Walk me through a significant software project you contributed to. What was the core problem and how did you architect the solution?"
            proj_name = "Project Experience"

        return GeneratedQuestion(
            id=qid,
            question=q_text,
            category="Technical",
            topic=proj_name,
            difficulty=difficulty,
            stage="PROJECT",
            focus="Project Experience",
            expected_aspects=["Address the specific question asked", "Support explanations with actual project experience"],
        )

    if stage == "ADVANCED_TECHNICAL":
        req_skills = job_profile.required_skills or ["Backend Engineering"]
        target_skill = req_skills[index % len(req_skills)]
        return GeneratedQuestion(
            id=qid,
            question=f"If traffic to your {target_skill} services grew by 100x, how would you architect caching, database queries, and rate limiting to ensure high scalability?",
            category="Technical",
            topic=f"{target_skill} Scalability",
            difficulty="Hard" if difficulty == "Hard" else "Medium",
            stage="ADVANCED_TECHNICAL",
            focus="System Scalability",
            expected_aspects=["Caching strategies and database query optimization", "Concurrency and latency trade-offs"],
        )

    # Default TECHNICAL_FUNDAMENTALS
    req_skills = job_profile.required_skills or ["Problem Solving"]
    target_skill = req_skills[index % len(req_skills)]
    return GeneratedQuestion(
        id=qid,
        question=f"Could you explain the fundamental principles of {target_skill} and how you evaluate trade-offs in a production environment?",
        category="Technical",
        topic=target_skill,
        difficulty=difficulty,
        stage="TECHNICAL_FUNDAMENTALS",
        focus="Technical Fundamentals",
        expected_aspects=[f"Foundational mechanics of {target_skill}", "Design trade-offs and best practices"],
    )


def extract_questions_list(raw_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Safely locate the list of question objects inside the model's raw response.
    """
    if "questions" in raw_dict and isinstance(raw_dict["questions"], list):
        return raw_dict["questions"]
    for key in ("interview_questions", "question_list", "data", "items"):
        if key in raw_dict and isinstance(raw_dict[key], list):
            return raw_dict[key]
    for val in raw_dict.values():
        if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
            return val
    return []


def calculate_question_generation_num_predict(question_count: int) -> int:
    bounded = max(1, min(15, question_count))
    if bounded <= 5:
        return 1000
    elif bounded <= 10:
        return 1800
    else:
        return 2600


@llm_usage.operation("bulk_questions")
async def generate_interview_questions(
    request: QuestionGenerationRequest,
) -> QuestionGenerationResponse:
    """
    Main orchestration function for Phase 7 personalized question generation.

    Enforces realistic interview flow:
        - Slot 1: ALWAYS Introduction (Question 1 Special Rule)
        - Pre-Project: Resume & Technical Fundamentals
        - Project: Natural project exploration
        - Advanced: Scalability and system design scenarios
    """
    start_time = time.perf_counter()

    if request.interview_type in ("HR", "Mixed"):
        # The historical bulk route uses the same plan and validated generator.
        from app.services.adaptive_interviewer import create_interview_plan, create_first_question, generate_single_next_question
        from app.services.question_policy import HR_TOPICS
        plan = create_interview_plan(candidate_profile=request.candidate_profile, job_profile=request.job_profile,
            analysis=request.analysis, interview_type=request.interview_type, question_count=request.question_count,
            difficulty=request.difficulty, role=request.job_profile.role_title)
        questions = [create_first_question(request.candidate_profile.candidate_name, request.interview_type)]
        projects = named_projects(plan["candidate_projects"])
        used_hr_topics = set()
        for index, slot in enumerate(plan["planned_sequence"][1:], 2):
            topic = slot["topic"]
            project = None
            if slot["category"] == "HR":
                if topic in used_hr_topics:
                    topic = next((t for t in HR_TOPICS if t not in used_hr_topics), topic)
                if topic == "Project experience":
                    project = resolve_project(projects, active_project=plan["active_project"])
            question, _ = await generate_single_next_question(decision="NEXT_TOPIC",
                stage="PROJECT_INTRO" if project else slot["stage"],
                target_skill=topic, target_concept=topic, difficulty=request.difficulty, project_context=project,
                category=slot["category"], role=request.job_profile.role_title,
                question_history=[q.question for q in questions], q_index=index)
            questions.append(question)
            if question.category == "HR":
                used_hr_topics.add(question.topic)
        return QuestionGenerationResponse(questions=questions, count=len(questions), interview_type=request.interview_type,
            difficulty=request.difficulty, role=request.job_profile.role_title,
            processing_time_ms=int((time.perf_counter() - start_time) * 1000))

    if request.subject:
        # Reuse the same scoped generator; no generic fallback may replace a
        # failed subject question in the backward-compatible bulk endpoint.
        from app.services.adaptive_interviewer import generate_single_next_question
        from app.services.question_policy import SUBJECT_TOPICS
        questions = []
        topics = SUBJECT_TOPICS[request.subject]
        for i in range(request.question_count):
            question, _ = await generate_single_next_question(
                decision="NEXT_TOPIC", stage="TECHNICAL_FUNDAMENTALS",
                target_skill=topics[i % len(topics)], target_concept=topics[i % len(topics)],
                difficulty=request.difficulty, category="Technical", role=request.job_profile.role_title,
                subject=request.subject, question_history=[q.question for q in questions], q_index=i + 1)
            questions.append(question)
        return QuestionGenerationResponse(questions=questions, count=len(questions),
            interview_type=request.interview_type, difficulty=request.difficulty,
            role=request.job_profile.role_title, processing_time_ms=int((time.perf_counter() - start_time) * 1000))

    expected_stages = determine_stage_sequence(request.question_count, request.interview_type)

    prompt, allowed_techs = build_question_generation_prompt(
        candidate_profile=request.candidate_profile,
        job_profile=request.job_profile,
        analysis=request.analysis,
        interview_type=request.interview_type,
        difficulty=request.difficulty,
        question_count=request.question_count,
    )

    num_tokens = calculate_question_generation_num_predict(request.question_count)

    llm_output = await llm_service.generate_json_response(
        prompt=prompt,
        think=False,
        num_predict=num_tokens,
        temperature=0.2,
    )

    raw_questions = extract_questions_list(llm_output)

    # -------------------------------------------------------------------------
    # Parse & Filter Raw Questions
    # -------------------------------------------------------------------------
    parsed_questions: list[GeneratedQuestion] = []
    seen_texts: list[str] = []

    for idx, item in enumerate(raw_questions):
        if not isinstance(item, dict):
            continue

        q_text = str(item.get("question", "")).strip()
        if not q_text or len(q_text) < 15:
            continue

        # Anti-hallucination
        if is_technology_hallucinated(q_text, allowed_techs):
            continue
        topic = str(item.get("topic", "General")).strip()
        if is_technology_hallucinated(topic, allowed_techs):
            continue

        # Duplicate check
        duplicate = False
        for seen in seen_texts:
            if is_near_duplicate(q_text, seen):
                duplicate = True
                break
        if duplicate:
            continue

        seen_texts.append(q_text)

        cat = str(item.get("category", "Technical")).strip()
        if request.interview_type == "Technical":
            cat = "Technical"
        elif request.interview_type == "HR":
            cat = "HR"
        elif cat.upper() == "HR":
            cat = "HR"
        else:
            cat = "Technical"

        aspects = item.get("expected_aspects", [])
        if isinstance(aspects, str):
            aspects = [aspects]
        elif not isinstance(aspects, list):
            aspects = ["Demonstrated technical clarity", "Practical problem solving"]
        aspects = [str(a).strip() for a in aspects if str(a).strip()]

        raw_stage = str(item.get("stage", "")).strip().upper()
        if raw_stage not in ("INTRO", "RESUME_JD", "TECHNICAL_FUNDAMENTALS", "PROJECT", "ADVANCED_TECHNICAL"):
            if is_introductory_question(q_text):
                raw_stage = "INTRO"
            elif is_project_question(q_text, request.candidate_profile):
                raw_stage = "PROJECT"
            elif is_advanced_question(q_text):
                raw_stage = "ADVANCED_TECHNICAL"
            else:
                raw_stage = "TECHNICAL_FUNDAMENTALS"

        project = resolve_project(request.candidate_profile.key_projects, topic=f"{topic} {q_text}")
        q_text = explicit_project_question(q_text, project, required=raw_stage == "PROJECT", category=cat)
        if raw_stage == "PROJECT" and not project:
            topic = "Project Experience"
            aspects = ["Address the specific question asked", "Support explanations with actual project experience"]
        parsed_q = GeneratedQuestion(
            id=f"q{len(parsed_questions) + 1}",
            question=q_text,
            category=cat,
            topic=topic or "General",
            difficulty=request.difficulty,
            stage=raw_stage,
            focus=str(item.get("focus", "General")).strip(),
            expected_aspects=aspects or ["Core conceptual understanding", "Practical application"],
        )
        parsed_questions.append(parsed_q)

    # -------------------------------------------------------------------------
    # Realistic Stage Assembly & Question 1 Special Rule Enforcement
    # -------------------------------------------------------------------------
    final_questions: list[GeneratedQuestion] = []
    used_topics: set[str] = set()

    # 1. SLOT 1: GUARANTEE INTRODUCTION QUESTION
    intro_candidates = [q for q in parsed_questions if is_introductory_question(q.question) or q.stage == "INTRO"]
    if intro_candidates:
        intro_q = intro_candidates[0]
        parsed_questions.remove(intro_q)
    else:
        # Generate pristine introductory question
        name_str = f"Hi {request.candidate_profile.candidate_name}, " if request.candidate_profile.candidate_name else "Hi, "
        intro_q = GeneratedQuestion(
            id="q1",
            question=f"{name_str}could you please introduce yourself and briefly walk me through your background?",
            category="HR" if request.interview_type in ("HR", "Mixed") else "Technical",
            stage="INTRO",
            topic="Candidate Introduction",
            difficulty="Easy",
            focus="Introduction",
            expected_aspects=[
                "Clear structured overview of background and experience",
                "Summary of key technical skills and career goals",
            ],
        )

    intro_q.id = "q1"
    intro_q.stage = "INTRO"
    intro_q.topic = "Candidate Introduction"
    intro_q.focus = "Introduction"
    intro_q.difficulty = "Easy"
    final_questions.append(intro_q)
    used_topics.add("candidate introduction")

    # 2. Partition remaining questions into buckets: Resume/Fundamentals, Project, Advanced
    fund_bucket = [
        q for q in parsed_questions
        if q.stage in ("RESUME_JD", "TECHNICAL_FUNDAMENTALS") and not is_project_question(q.question, request.candidate_profile) and not is_introductory_question(q.question)
    ]
    proj_bucket = [
        q for q in parsed_questions
        if q.stage == "PROJECT" or is_project_question(q.question, request.candidate_profile)
    ]
    adv_bucket = [
        q for q in parsed_questions
        if q.stage == "ADVANCED_TECHNICAL" or is_advanced_question(q.question)
    ]
    # Other parsed questions not in the above buckets
    other_bucket = [
        q for q in parsed_questions
        if q not in fund_bucket and q not in proj_bucket and q not in adv_bucket and not is_introductory_question(q.question)
    ]
    fund_bucket.extend(other_bucket)

    # 3. Assemble slots 2..N strictly matching expected_stages
    for slot_idx in range(1, request.question_count):
        stage_needed = expected_stages[slot_idx]
        chosen_q = None

        if stage_needed in ("RESUME_JD", "TECHNICAL_FUNDAMENTALS"):
            if fund_bucket:
                chosen_q = fund_bucket.pop(0)
            elif adv_bucket:
                chosen_q = adv_bucket.pop(0)

        elif stage_needed == "PROJECT":
            if proj_bucket:
                chosen_q = proj_bucket.pop(0)
            elif fund_bucket:
                chosen_q = fund_bucket.pop(0)

        elif stage_needed == "ADVANCED_TECHNICAL":
            if adv_bucket:
                chosen_q = adv_bucket.pop(0)
            elif fund_bucket:
                chosen_q = fund_bucket.pop(0)

        # Fallback if bucket was empty
        if not chosen_q:
            chosen_q = generate_fallback_question(
                index=slot_idx,
                candidate_profile=request.candidate_profile,
                job_profile=request.job_profile,
                analysis=request.analysis,
                interview_type=request.interview_type,
                difficulty=request.difficulty,
                used_topics=used_topics,
                stage=stage_needed,
            )

        chosen_q.id = f"q{slot_idx + 1}"
        chosen_q.stage = stage_needed
        used_topics.add(chosen_q.topic.lower())
        final_questions.append(chosen_q)

    processing_time_ms = int((time.perf_counter() - start_time) * 1000)

    return QuestionGenerationResponse(
        success=True,
        questions=final_questions,
        count=len(final_questions),
        interview_type=request.interview_type,
        difficulty=request.difficulty,
        role=request.job_profile.role_title,
        processing_time_ms=processing_time_ms,
    )
