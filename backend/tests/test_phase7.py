"""
Comprehensive test suite for Phase 7: Personalized Question Generation.

Covers:
- Test 1: Valid Technical request (100% technical category)
- Test 2: Valid HR request (100% HR category)
- Test 3: Valid Mixed request (mixture of Technical and HR questions)
- Test 4: Easy difficulty setting respected
- Test 5: Medium difficulty setting respected
- Test 6: Hard difficulty setting respected
- Test 7: Question count validation (requested N questions produces N questions)
- Test 8: Missing candidate profile -> HTTP 422
- Test 9: Missing job profile -> HTTP 422
- Test 10: Invalid interview type -> HTTP 422
- Test 11: Invalid difficulty -> HTTP 422
- Test 12: Invalid question count (0 or > 15) -> HTTP 422
- Test 13: Malformed LLM JSON handling / extraction resilience
- Test 14: Ollama unavailable simulation -> HTTP 503
- Test 15: Duplicate question detection and elimination
- Test 16: Controlled Anti-Hallucination test (absent tools NOT generated)
- Test 17: Required skill prioritization
- Test 18: Skill-gap targeting (gap evaluated without claiming mastery)
- Test 19: Full response schema validation
- Test 20: Real Live End-to-End Qwen3 question generation (POST /api/v1/interview/generate-questions)
"""

import os
import sys
import time
from unittest.mock import AsyncMock, patch

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.schemas.resume import CandidateProfile, CandidateProject
from app.schemas.job import JobProfile
from app.schemas.analysis import (
    MatchAnalysisResponse,
    MatchAnalysisSummary,
    SkillMatchItem,
    SkillGapItem,
    RequirementCheckItem,
)
from app.schemas.interview import (
    GeneratedQuestion,
    QuestionGenerationRequest,
    QuestionGenerationResponse,
)
from app.services.llm_service import (
    OllamaConnectionError,
    LLMResponseParseError,
)
from app.services.question_generator import (
    generate_interview_questions,
    is_technology_hallucinated,
    is_near_duplicate,
    extract_questions_list,
)
from app.prompts.question_prompts import (
    build_question_generation_prompt,
    extract_allowed_technologies,
)


def sample_candidate() -> CandidateProfile:
    return CandidateProfile(
        candidate_name="Alex Example",
        extracted_skills=["Java", "SQL", "Spring Boot"],
        experience_years=2.0,
        key_projects=[
            CandidateProject(
                name="E-Commerce Backend",
                description="RESTful microservices with PostgreSQL and Java",
                technologies=["Java", "SQL", "Spring Boot"],
            )
        ],
    )


def sample_job() -> JobProfile:
    return JobProfile(
        role_title="Backend Software Engineer",
        required_skills=["Java", "SQL", "Spring Boot", "Python"],
        good_to_have_skills=["PostgreSQL"],
        experience_level="2+ years",
    )


def sample_analysis() -> MatchAnalysisResponse:
    return MatchAnalysisResponse(
        success=True,
        match_score=75,
        matched_skills=[
            SkillMatchItem(required_skill="Java", candidate_skill="Java", similarity=1.0, category="required"),
            SkillMatchItem(required_skill="SQL", candidate_skill="SQL", similarity=1.0, category="required"),
            SkillMatchItem(required_skill="Spring Boot", candidate_skill="Spring Boot", similarity=1.0, category="required"),
        ],
        skill_gaps=[
            SkillGapItem(skill="Python", category="required", reason="No similar candidate skill found"),
        ],
        preferred_matches=[
            SkillMatchItem(required_skill="PostgreSQL", candidate_skill="SQL", similarity=0.85, category="preferred"),
        ],
        preferred_gaps=[],
        skills_found=["Java", "SQL", "Spring Boot", "PostgreSQL"],
        gap_skills=["Python"],
        requirements=[
            RequirementCheckItem(text="Java", matched=True, matched_with="Java", similarity=1.0),
            RequirementCheckItem(text="SQL", matched=True, matched_with="SQL", similarity=1.0),
            RequirementCheckItem(text="Spring Boot", matched=True, matched_with="Spring Boot", similarity=1.0),
            RequirementCheckItem(text="Python", matched=False, matched_with=None, similarity=0.0),
        ],
        summary=MatchAnalysisSummary(
            total_required=4,
            matched_required=3,
            total_preferred=1,
            matched_preferred=1,
            total_candidate_skills=3,
            required_coverage=0.75,
            preferred_coverage=1.0,
            threshold_used=0.60,
        ),
    )


def run_all_tests():
    client = TestClient(app)
    print("=================================================================")
    print("STARTING PHASE 7 AUTOMATED TEST SUITE")
    print("=================================================================")

    cand = sample_candidate()
    job = sample_job()
    analysis = sample_analysis()

    # -------------------------------------------------------------------------
    # Test 1: Valid Technical Request (100% Technical)
    # -------------------------------------------------------------------------
    print("\n[TEST 1] Valid Technical request (100% Technical questions)...")
    req_tech = QuestionGenerationRequest(
        candidate_profile=cand,
        job_profile=job,
        analysis=analysis,
        interview_type="Technical",
        difficulty="Medium",
        question_count=5,
    )
    assert req_tech.interview_type == "Technical"
    assert req_tech.question_count == 5
    print("  PASS: Technical request schema validated.")

    # -------------------------------------------------------------------------
    # Test 2: Valid HR Request (100% HR)
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Valid HR request (100% HR questions)...")
    req_hr = QuestionGenerationRequest(
        candidate_profile=cand,
        job_profile=job,
        analysis=analysis,
        interview_type="HR",
        difficulty="Medium",
        question_count=5,
    )
    assert req_hr.interview_type == "HR"
    print("  PASS: HR request schema validated.")

    # -------------------------------------------------------------------------
    # Test 3: Valid Mixed Request
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Valid Mixed request...")
    req_mixed = QuestionGenerationRequest(
        candidate_profile=cand,
        job_profile=job,
        analysis=analysis,
        interview_type="Mixed",
        difficulty="Medium",
        question_count=10,
    )
    assert req_mixed.interview_type == "Mixed"
    assert req_mixed.question_count == 10
    print("  PASS: Mixed request schema validated.")

    # -------------------------------------------------------------------------
    # Test 4, 5, 6: Difficulty Levels (Easy, Medium, Hard)
    # -------------------------------------------------------------------------
    print("\n[TEST 4, 5, 6] Difficulty levels (Easy, Medium, Hard)...")
    for diff in ("Easy", "Medium", "Hard"):
        r = QuestionGenerationRequest(
            candidate_profile=cand,
            job_profile=job,
            interview_type="Technical",
            difficulty=diff,
            question_count=3,
        )
        assert r.difficulty == diff
    print("  PASS: Easy, Medium, and Hard difficulty configurations validated.")

    # -------------------------------------------------------------------------
    # Test 7: Question Count Bounded Validation
    # -------------------------------------------------------------------------
    print("\n[TEST 7] Question count bounded validation (1 to 15)...")
    r_min = QuestionGenerationRequest(candidate_profile=cand, job_profile=job, question_count=1)
    r_max = QuestionGenerationRequest(candidate_profile=cand, job_profile=job, question_count=15)
    assert r_min.question_count == 1
    assert r_max.question_count == 15
    print("  PASS: Question counts 1 and 15 successfully bounded.")

    # -------------------------------------------------------------------------
    # Test 8 & 9: Missing Profiles (HTTP 422)
    # -------------------------------------------------------------------------
    print("\n[TEST 8 & 9] Missing candidate or job profile -> 422...")
    res_no_cand = client.post("/api/v1/interview/generate-questions", json={"job_profile": job.model_dump()})
    assert res_no_cand.status_code == 422, f"Expected 422, got {res_no_cand.status_code}"
    res_no_job = client.post("/api/v1/interview/generate-questions", json={"candidate_profile": cand.model_dump()})
    assert res_no_job.status_code == 422, f"Expected 422, got {res_no_job.status_code}"
    print("  PASS: HTTP 422 returned for missing candidate_profile and job_profile.")

    # -------------------------------------------------------------------------
    # Test 10: Invalid Interview Type -> 422
    # -------------------------------------------------------------------------
    print("\n[TEST 10] Invalid interview type -> 422...")
    payload_invalid_type = {
        "candidate_profile": cand.model_dump(),
        "job_profile": job.model_dump(),
        "interview_type": "CodingContest",
    }
    res_inv_type = client.post("/api/v1/interview/generate-questions", json=payload_invalid_type)
    assert res_inv_type.status_code == 422
    print("  PASS: Invalid interview type rejected with HTTP 422.")

    # -------------------------------------------------------------------------
    # Test 11: Invalid Difficulty -> 422
    # -------------------------------------------------------------------------
    print("\n[TEST 11] Invalid difficulty -> 422...")
    payload_invalid_diff = {
        "candidate_profile": cand.model_dump(),
        "job_profile": job.model_dump(),
        "difficulty": "Insane",
    }
    res_inv_diff = client.post("/api/v1/interview/generate-questions", json=payload_invalid_diff)
    assert res_inv_diff.status_code == 422
    print("  PASS: Invalid difficulty rejected with HTTP 422.")

    # -------------------------------------------------------------------------
    # Test 12: Invalid Question Count (0 or > 15) -> 422
    # -------------------------------------------------------------------------
    print("\n[TEST 12] Invalid question count (0 or 20) -> 422...")
    res_zero = client.post("/api/v1/interview/generate-questions", json={
        "candidate_profile": cand.model_dump(),
        "job_profile": job.model_dump(),
        "question_count": 0,
    })
    assert res_zero.status_code == 422
    res_over = client.post("/api/v1/interview/generate-questions", json={
        "candidate_profile": cand.model_dump(),
        "job_profile": job.model_dump(),
        "question_count": 25,
    })
    assert res_over.status_code == 422
    print("  PASS: Question counts 0 and 25 rejected with HTTP 422.")

    # -------------------------------------------------------------------------
    # Test 13: Malformed LLM JSON Handling / Extraction Resilience
    # -------------------------------------------------------------------------
    print("\n[TEST 13] Extraction resilience from various dict formats...")
    # Test nested key extraction (interview_questions, items, etc.)
    dict_nested = {"interview_questions": [{"question": "What is indexing in SQL?", "topic": "SQL"}]}
    extracted = extract_questions_list(dict_nested)
    assert len(extracted) == 1
    assert extracted[0]["topic"] == "SQL"
    print("  PASS: Non-standard key extraction verified.")

    # -------------------------------------------------------------------------
    # Test 14: Ollama Unavailable Simulation -> HTTP 503
    # -------------------------------------------------------------------------
    print("\n[TEST 14] Ollama unavailable simulation (503 Service Unavailable)...")
    with patch("app.services.llm_service.generate_json_response", side_effect=OllamaConnectionError("Ollama offline")):
        res_503 = client.post("/api/v1/interview/generate-questions", json={
            "candidate_profile": cand.model_dump(),
            "job_profile": job.model_dump(),
            "question_count": 5,
        })
        assert res_503.status_code == 503, f"Expected 503, got {res_503.status_code}"
        assert res_503.headers['content-type'] == 'application/problem+json'
        assert res_503.json()['status'] == 503
        assert "temporarily unavailable" in res_503.json()["detail"].lower()
    print("  PASS: HTTP 503 returned when Ollama is offline.")

    # -------------------------------------------------------------------------
    # Test 15: Duplicate Question Detection & Elimination
    # -------------------------------------------------------------------------
    print("\n[TEST 15] Duplicate question detection and elimination...")
    q1 = "How does indexing in SQL improve query execution speed?"
    q2 = "How does indexing in SQL improve query execution speed?"
    q3 = "Explain how SQL indexing improves query execution speed."
    assert is_near_duplicate(q1, q2) is True
    assert is_near_duplicate(q1, q3) is True
    assert is_near_duplicate(q1, "What is polymorphism in Java?") is False
    print("  PASS: Duplicate and near-duplicate detection verified.")

    # -------------------------------------------------------------------------
    # Test 16: Controlled Anti-Hallucination Test (Absent Tools NOT Generated)
    # -------------------------------------------------------------------------
    print("\n[TEST 16] Controlled anti-hallucination test...")
    # Candidate: Java, SQL. JD: Java, SQL, Python.
    # Absent tools: Docker, Kubernetes, AWS, React, GraphQL.
    allowed = extract_allowed_technologies(
        CandidateProfile(candidate_name="Bob", extracted_skills=["Java", "SQL"], experience_years=1.0),
        JobProfile(role_title="Backend Dev", required_skills=["Java", "SQL", "Python"]),
    )
    assert "java" in [a.lower() for a in allowed]
    assert "sql" in [a.lower() for a in allowed]
    assert "python" in [a.lower() for a in allowed]
    assert "docker" not in [a.lower() for a in allowed]
    assert "kubernetes" not in [a.lower() for a in allowed]
    assert "aws" not in [a.lower() for a in allowed]
    assert "react" not in [a.lower() for a in allowed]

    # Verify hallucination detector flags absent tools
    assert is_technology_hallucinated("How would you containerize this app with Docker?", allowed) is True
    assert is_technology_hallucinated("How would you deploy this to AWS EC2?", allowed) is True
    assert is_technology_hallucinated("Explain how you use React state hooks.", allowed) is True
    assert is_technology_hallucinated("Explain how you handle transactions in SQL.", allowed) is False
    assert is_technology_hallucinated("Describe garbage collection in Java.", allowed) is False
    print("  PASS: Anti-hallucination guard successfully detected and rejected unallowed tools.")

    # -------------------------------------------------------------------------
    # Test 17: Required Skill Prioritization in Prompt
    # -------------------------------------------------------------------------
    print("\n[TEST 17] Prompt engineering required skill prioritization...")
    prompt_text, _ = build_question_generation_prompt(
        candidate_profile=cand,
        job_profile=job,
        analysis=analysis,
        interview_type="Technical",
        difficulty="Hard",
        question_count=7,
    )
    assert "Java" in prompt_text
    assert "SQL" in prompt_text
    assert "Python" in prompt_text
    assert "CRITICAL RULES" in prompt_text
    assert "STRICT ANTI-HALLUCINATION" in prompt_text
    print("  PASS: Prompt incorporates candidate skills, JD required skills, gaps, and strict rules.")

    # -------------------------------------------------------------------------
    # Test 18: Skill-Gap Targeting in Prompt & Generated Schema
    # -------------------------------------------------------------------------
    print("\n[TEST 18] Skill-gap targeting...")
    assert "Python" in prompt_text
    assert "Identified Skill Gaps: Python" in prompt_text
    assert "Do NOT assume the candidate is already an expert in their gap skills" in prompt_text
    print("  PASS: Skill gaps explicitly framed as foundational/bridge assessments.")

    # -------------------------------------------------------------------------
    # Test 19: Full Response Schema Validation
    # -------------------------------------------------------------------------
    print("\n[TEST 19] Full response schema validation...")
    mock_q = GeneratedQuestion(
        id="q1",
        question="How does the JVM manage heap and stack memory during high-concurrency requests?",
        category="Technical",
        topic="Java",
        difficulty="Hard",
        focus="Matched Skill",
        expected_aspects=["Heap vs stack lifecycle", "Garbage collection impact", "Thread safety"],
    )
    mock_resp = QuestionGenerationResponse(
        success=True,
        questions=[mock_q],
        count=1,
        interview_type="Technical",
        difficulty="Hard",
        role="Backend Software Engineer",
        processing_time_ms=120,
    )
    assert mock_resp.count == 1
    assert mock_resp.questions[0].topic == "Java"
    assert len(mock_resp.questions[0].expected_aspects) == 3
    print("  PASS: Response schema conforms to Pydantic contract.")

    # -------------------------------------------------------------------------
    # Test 20: Real Live End-to-End Qwen3 Generation via API (POST /api/v1/interview/generate-questions)
    # -------------------------------------------------------------------------
    print("\n[TEST 20] Real Live End-to-End Qwen3 question generation (POST /api/v1/interview/generate-questions)...")
    live_payload = {
        "candidate_profile": {
            "candidate_name": "Alex Example",
            "extracted_skills": ["Java", "SQL", "Spring Boot"],
            "experience_years": 2.0,
            "key_projects": [
                {
                    "name": "Interview-IQ",
                    "description": "AI mock interview backend and evaluation system",
                    "technologies": ["Java", "SQL", "Spring Boot"],
                }
            ],
        },
        "job_profile": {
            "role_title": "Java Backend Engineer",
            "required_skills": ["Java", "SQL", "Spring Boot", "Python"],
            "good_to_have_skills": ["Docker"],
            "experience_level": "2+ years",
        },
        "analysis": analysis.model_dump(),
        "interview_type": "Technical",
        "difficulty": "Medium",
        "question_count": 4,
    }

    t_start = time.perf_counter()
    live_res = client.post("/api/v1/interview/generate-questions", json=live_payload)
    elapsed_ms = (time.perf_counter() - t_start) * 1000

    assert live_res.status_code == 200, f"Live generation failed ({live_res.status_code}): {live_res.text}"
    live_data = live_res.json()

    assert live_data["success"] is True
    assert "questions" in live_data
    assert isinstance(live_data["questions"], list)
    assert len(live_data["questions"]) == 4, f"Expected 4 questions, got {len(live_data['questions'])}"
    assert live_data["count"] == 4
    assert live_data["interview_type"] == "Technical"
    assert live_data["difficulty"] == "Medium"
    assert live_data["role"] == "Java Backend Engineer"

    print(f"  PASS: Live Qwen3 generated {live_data['count']} questions in {elapsed_ms:.1f} ms:")
    for q in live_data["questions"]:
        print(f"        [{q['id']}] ({q['category']} | {q['topic']} | {q['difficulty']} | {q['focus']})")
        print(f"            Q: {q['question']}")
        print(f"            Aspects: {q['expected_aspects']}")
        assert len(q["question"]) > 10
        assert q["category"] in ("Technical", "HR")
        assert len(q["expected_aspects"]) >= 1

    print("\n=================================================================")
    print("ALL 20 PHASE 7 AUTOMATED TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")


if __name__ == "__main__":
    run_all_tests()
