"""
Prompt templates and builders for Personalized Question Generation with Qwen3.
"""

import json
from app.schemas.resume import CandidateProfile
from app.schemas.job import JobProfile
from app.schemas.analysis import MatchAnalysisResponse


def extract_allowed_technologies(
    candidate_profile: CandidateProfile,
    job_profile: JobProfile,
    analysis: MatchAnalysisResponse | None = None,
) -> list[str]:
    """
    Extract a unique, normalized whitelist of technologies present in the supplied
    candidate profile, job description, and semantic analysis.
    """
    techs = set()

    # From candidate skills
    for s in candidate_profile.extracted_skills:
        clean = str(s).strip()
        if clean:
            techs.add(clean)

    # From candidate projects
    for p in candidate_profile.key_projects:
        for t in p.technologies:
            clean = str(t).strip()
            if clean:
                techs.add(clean)

    # From JD required skills
    for s in job_profile.required_skills:
        clean = str(s).strip()
        if clean:
            techs.add(clean)

    # From JD preferred skills
    for s in job_profile.good_to_have_skills:
        clean = str(s).strip()
        if clean:
            techs.add(clean)

    # From analysis matched skills and gaps
    if analysis:
        for m in analysis.matched_skills:
            techs.add(m.required_skill)
            techs.add(m.candidate_skill)
        for g in analysis.skill_gaps:
            techs.add(g.skill)
        for s in analysis.skills_found:
            techs.add(s)
        for s in analysis.gap_skills:
            techs.add(s)

    return sorted(list(techs), key=lambda x: x.lower())


def build_question_generation_prompt(
    candidate_profile: CandidateProfile,
    job_profile: JobProfile,
    analysis: MatchAnalysisResponse | None,
    interview_type: str,
    difficulty: str,
    question_count: int,
) -> tuple[str, list[str]]:
    """
    Construct a comprehensive, context-aware prompt for Qwen3 to generate
    personalized interview questions tailored to the candidate's resume,
    target job description, matched competencies, and identified skill gaps.

    Returns
    -------
    tuple[str, list[str]]
        The prompt string and the whitelist of allowed technologies.
    """
    allowed_techs = extract_allowed_technologies(candidate_profile, job_profile, analysis)

    # Extract matched skills and skill gaps
    matched_skill_names = []
    gap_skill_names = []
    if analysis:
        matched_skill_names = [m.required_skill for m in analysis.matched_skills]
        gap_skill_names = [g.skill for g in analysis.skill_gaps]
    else:
        # Fallback comparison if analysis not pre-computed
        cand_lower = {s.lower() for s in candidate_profile.extracted_skills}
        for s in job_profile.required_skills:
            if s.lower() in cand_lower:
                matched_skill_names.append(s)
            else:
                gap_skill_names.append(s)

    # Project context
    projects_summary = []
    for p in candidate_profile.key_projects[:3]:
        tech_str = ", ".join(p.technologies) if p.technologies else "None specified"
        projects_summary.append(f"- {p.name}: {p.description} (Tech: {tech_str})")
    projects_text = "\n".join(projects_summary) if projects_summary else "No specific projects listed."

    # Interview type guidelines
    type_instruction = ""
    if interview_type == "Technical":
        type_instruction = (
            "Focus 100% on technical skills, architecture, debugging, implementation, "
            "and technical project problem-solving. Every question must be categorized as 'Technical'."
        )
    elif interview_type == "HR":
        type_instruction = (
            "Focus 100% on behavioral competencies, collaboration, communication, handling pressure, "
            "project contributions, conflict resolution, and career motivation using the candidate's "
            "actual background. Every question must be categorized as 'HR'."
        )
    else:  # Mixed
        tech_qty = max(1, round(question_count * 0.70))
        hr_qty = question_count - tech_qty
        type_instruction = (
            f"Provide a balanced mix of approximately {tech_qty} 'Technical' questions and {hr_qty} 'HR' "
            "(behavioral/project experience) questions."
        )

    # Difficulty guidelines
    diff_instruction = ""
    if difficulty == "Easy":
        diff_instruction = "Focus on core fundamentals, definitions, clear practical syntax, and basic concepts."
    elif difficulty == "Medium":
        diff_instruction = "Focus on practical application, design decisions, troubleshooting, and real-world scenarios."
    else:  # Hard
        diff_instruction = "Focus on deep technical reasoning, trade-offs, scalability, edge cases, and complex architecture."

    # Realistic interview stage progression guidelines
    stage_guidance = (
        "MANDATORY REALISTIC INTERVIEW FLOW & STAGE PROGRESSION:\n"
        "1. QUESTION 1 MUST BE AN INTRODUCTION (Stage: 'INTRO'):\n"
        f"   - Question 1 MUST be a natural, welcoming introductory question asking {candidate_profile.candidate_name or 'the candidate'} to introduce themselves and walk through their background.\n"
        "   - Example: 'Could you please introduce yourself and briefly walk me through your background?'\n"
        "   - NEVER ask a project deep-dive, database schema, or complex technical question in Question 1.\n"
        "   - stage: 'INTRO', topic: 'Candidate Introduction', difficulty: 'Easy', focus: 'Introduction'.\n\n"
        "2. STAGE 2 — RESUME & JD ALIGNMENT / FUNDAMENTALS (Stage: 'RESUME_JD' or 'TECHNICAL_FUNDAMENTALS'):\n"
        "   - Questions following introduction must establish understanding of core technologies listed on the candidate's resume and required by the JD.\n"
        "   - Test foundational mechanics (e.g. OOP, REST API principles, query fundamentals) BEFORE moving to projects.\n\n"
        "3. STAGE 3 — PROJECT EXPERIENCE (Stage: 'PROJECT'):\n"
        "   - Only after establishing fundamentals, introduce the candidate's actual named projects from the supplied resume.\n"
        "   - Introduce projects NATURALLY: First ask what problem the project solves and the candidate's contribution, then discuss backend architecture and technology choices (e.g. why MongoDB), and then deeper design.\n"
        "   - DO NOT start with complex schema optimization before asking for project context.\n\n"
        "4. STAGE 4 — ADVANCED TECHNICAL & SCALABILITY (Stage: 'ADVANCED_TECHNICAL'):\n"
        "   - Toward the end of the interview, increase technical depth: API scalability, caching, load balancing, system design scenarios, and architectural trade-offs.\n"
    )

    allowed_techs_formatted = ", ".join(allowed_techs) if allowed_techs else "General Software Engineering Concepts"

    prompt = f"""You are an expert interviewer conducting a personalized interview for the role of '{job_profile.role_title}'.

Generate EXACTLY {question_count} personalized interview questions based on the candidate's resume and job requirements.
The interview MUST behave like a REAL, professional interview following a natural progression from introduction to fundamentals to project to advanced technical topics.

CANDIDATE CONTEXT:
- Candidate Name: {candidate_profile.candidate_name}
- Total Experience: {candidate_profile.experience_years} years
- Resume Skills: {', '.join(candidate_profile.extracted_skills) if candidate_profile.extracted_skills else 'None specified'}
- Candidate Projects:
{projects_text}

TARGET JOB CONTEXT:
- Role Title: {job_profile.role_title}
- Required Experience: {job_profile.experience_level}
- Required Skills: {', '.join(job_profile.required_skills) if job_profile.required_skills else 'None specified'}
- Good-to-Have Skills: {', '.join(job_profile.good_to_have_skills) if job_profile.good_to_have_skills else 'None'}

MATCH & GAP ANALYSIS:
- Matched Competencies: {', '.join(matched_skill_names) if matched_skill_names else 'None'}
- Identified Skill Gaps: {', '.join(gap_skill_names) if gap_skill_names else 'None'}
  (Note: Do NOT assume the candidate is already an expert in their gap skills; frame any gap questions around foundational understanding or bridging concepts.)

ALLOWED TECHNOLOGIES WHITELIST:
[{allowed_techs_formatted}]

INTERVIEW CONFIGURATION:
- Interview Type: {interview_type} ({type_instruction})
- Target Difficulty: {difficulty} ({diff_instruction})
- Total Questions Requested: {question_count}

{stage_guidance}

CRITICAL RULES:
1. QUESTION 1 IS AN INTRODUCTION: Question 1 MUST ALWAYS be an introductory question asking for a background walkthrough. Never ask about database schemas or project implementations first.
2. RELEVANCE: Every question must relate directly to the target role of '{job_profile.role_title}' and the candidate's background.
3. NATURAL PROGRESSION: Progress logically: Introduction -> Resume/JD Fundamentals -> Project Experience -> Advanced Scalability.
4. STRICT ANTI-HALLUCINATION: Do NOT mention, ask about, or introduce any specific technologies, tools, or frameworks outside the ALLOWED TECHNOLOGIES WHITELIST.
5. NO DUPLICATES: Every question must be distinct and explore a different topic or competency.
6. DIFFICULTY: Calibrate questions appropriately according to stage and requested '{difficulty}' difficulty.
7. CONCISE OUTPUT: Keep each question text concise and direct (1-2 sentences). Keep each expected aspect to a brief phrase (max 12 words each).
8. PROJECT CONTEXT: Put the actual supplied project name in project-specific question text, not just its topic. Use only the supplied descriptions and technologies; ask about the candidate's work without inventing contributions or metrics. If no project can be identified, ask the candidate to choose one. Leave unrelated conceptual questions natural.
9. EXPECTED ASPECTS: Match only what the question actually asks. Do not require details merely because they appear in the planned topic or project description.
8. FORMAT: Return ONLY a valid JSON object matching the schema below. No markdown fences, no conversational text.

REQUIRED JSON SCHEMA:
{{
  "questions": [
    {{
      "id": "q1",
      "question": "Could you please introduce yourself and briefly walk me through your background?",
      "category": "Technical or HR",
      "stage": "INTRO",
      "topic": "Candidate Introduction",
      "difficulty": "Easy",
      "focus": "Introduction",
      "expected_aspects": [
        "Clear structured overview of background and experience",
        "Key technical skills and career interests"
      ]
    }},
    {{
      "id": "q2",
      "question": "Question text based on resume/JD fundamentals",
      "category": "Technical or HR",
      "stage": "RESUME_JD",
      "topic": "Specific skill or topic",
      "difficulty": "{difficulty}",
      "focus": "Matched Skill | Skill Gap | Project Experience | Behavioral",
      "expected_aspects": [
        "Key point 1 expected in a solid answer",
        "Key point 2 expected in a solid answer"
      ]
    }}
  ]
}}"""

    return prompt, allowed_techs
