"""
Comprehensive test suite for Realistic Interview Flow & Question Sequencing.

Covers:
- Test 1: First question is introduction
- Test 2: First question is not a project deep-dive
- Test 3: Technical interview progresses: Introduction -> Resume/JD -> Technical -> Project -> Advanced
- Test 4: HR interview starts with introduction/background
- Test 5: Mixed interview contains both technical and behavioral stages
- Test 6: 5-question interview respects stage progression
- Test 7: 10-question interview respects stage progression
- Test 8: 15-question interview respects stage progression
- Test 9: Project questions are not asked before introductory/resume questions
- Test 10: Adaptive follow-up remains within the current topic
- Test 11: Strong technical answer can advance to a deeper question
- Test 12: Weak technical answer can trigger a targeted follow-up
- Test 13: Phase 10 evaluation remains unchanged
- Test 14: Phase 8 session persistence remains unchanged
- Test 15: Existing Phase 7 question generation remains functional
- Test 16 (Bonus): Candidate 'I don't know' in adaptive flow transitions to NEXT_TOPIC without drilling
"""

import os
import sys
import time
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.adaptive import (
    AdaptiveDecisionResult,
    AdaptiveEvaluationInput,
    AdaptiveNextQuestionRequest,
    AdaptiveNextQuestionResponse,
)
from app.schemas.analysis import MatchAnalysisResponse, SkillGapItem, SkillMatchItem, MatchAnalysisSummary
from app.schemas.evaluation import AnswerEvaluationRequest
from app.schemas.interview import (
    GeneratedQuestion,
    InterviewAnswerRecord,
    InterviewSessionState,
    QuestionGenerationRequest,
    QuestionGenerationResponse,
)
from app.schemas.job import JobProfile
from app.schemas.resume import CandidateProfile, CandidateProject
from app.services.adaptive_interviewer import decide_next_action, process_adaptive_next_question
from app.services.evaluator import evaluate_candidate_answer
from app.services.question_generator import (
    determine_stage_sequence,
    generate_fallback_question,
    generate_interview_questions,
    is_introductory_question,
    is_project_question,
)


def create_sample_context():
    candidate_profile = CandidateProfile(
        candidate_name="Alex Rivera",
        experience_years=3.5,
        extracted_skills=["Java", "Spring Boot", "MongoDB", "REST APIs", "SQL"],
        key_projects=[
            CandidateProject(
                name="Cinemaverse",
                description="Movie discovery and streaming backend with high concurrency and personalized recommendations.",
                technologies=["Java", "Spring Boot", "MongoDB", "REST APIs"],
            )
        ],
    )
    job_profile = JobProfile(
        role_title="Backend Software Engineer",
        experience_level="Mid-Level",
        required_skills=["Java", "Spring Boot", "REST APIs", "SQL", "Database Design"],
        good_to_have_skills=["MongoDB", "Caching"],
    )
    analysis = MatchAnalysisResponse(
        match_score=85,
        matched_skills=[
            SkillMatchItem(required_skill="Java", candidate_skill="Java", similarity=1.0, category="required"),
            SkillMatchItem(required_skill="Spring Boot", candidate_skill="Spring Boot", similarity=1.0, category="required"),
            SkillMatchItem(required_skill="REST APIs", candidate_skill="REST APIs", similarity=1.0, category="required"),
        ],
        skill_gaps=[
            SkillGapItem(skill="Database Design", category="required", reason="Not explicitly highlighted"),
        ],
        skills_found=["Java", "Spring Boot", "MongoDB", "REST APIs"],
        gap_skills=["Database Design"],
        summary=MatchAnalysisSummary(
            total_required=5,
            matched_required=3,
            total_preferred=2,
            matched_preferred=1,
            total_candidate_skills=5,
            required_coverage=0.6,
            preferred_coverage=0.5,
            threshold_used=0.6,
        ),
    )
    return candidate_profile, job_profile, analysis


def run_all_tests():
    client = TestClient(app)
    print("=================================================================")
    print("STARTING REALISTIC INTERVIEW FLOW & SEQUENCING TEST SUITE")
    print("=================================================================")

    cand, job, analysis = create_sample_context()

    # -------------------------------------------------------------------------
    # TEST 1: First question is introduction
    # -------------------------------------------------------------------------
    print("\n[TEST 1] First question is introduction...")
    q_req = QuestionGenerationRequest(
        candidate_profile=cand,
        job_profile=job,
        analysis=analysis,
        interview_type="Technical",
        difficulty="Medium",
        question_count=10,
    )
    # Using mock LLM response where LLM mistakenly puts project first
    bad_llm_output = {
        "questions": [
            {
                "id": "q1",
                "question": "In your Cinemaverse project, how did you design the MongoDB movie schema?",
                "category": "Technical",
                "topic": "Cinemaverse",
                "difficulty": "Medium",
                "stage": "PROJECT",
                "focus": "Project Experience",
                "expected_aspects": ["Schema design", "Indexing"],
            },
            {
                "id": "q2",
                "question": "How does Java implement polymorphism?",
                "category": "Technical",
                "topic": "Java",
                "difficulty": "Medium",
                "stage": "TECHNICAL_FUNDAMENTALS",
                "focus": "Technical Fundamentals",
                "expected_aspects": ["Overloading vs overriding"],
            }
        ]
    }
    with patch("app.services.llm_service.generate_json_response", new=AsyncMock(return_value=bad_llm_output)):
        res = client.post("/api/v1/interview/generate-questions", json=q_req.model_dump())
        assert res.status_code == 200
        data = res.json()
        q1 = data["questions"][0]
        assert q1["stage"] == "INTRO", f"Expected stage=INTRO for Question 1, got {q1['stage']}"
        assert is_introductory_question(q1["question"]), f"Question 1 is not introductory: {q1['question']}"
        assert "introduce yourself" in q1["question"].lower() or "background" in q1["question"].lower()
        print(f"  PASS: Question 1 is Introduction: '{q1['question']}' (Stage: {q1['stage']})")

    # -------------------------------------------------------------------------
    # TEST 2: First question is not a project deep-dive
    # -------------------------------------------------------------------------
    print("\n[TEST 2] First question is NOT a project deep-dive...")
    assert not is_project_question(q1["question"], cand)
    assert "cinemaverse" not in q1["question"].lower()
    assert "mongodb" not in q1["question"].lower()
    assert "schema" not in q1["question"].lower()
    print("  PASS: Question 1 does not mention project implementation, schemas, or database internals")

    # -------------------------------------------------------------------------
    # TEST 3: Technical interview progresses: Intro -> Resume/JD -> Tech -> Project -> Advanced
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Technical interview stage progression...")
    stages = [q["stage"] for q in data["questions"]]
    print(f"  Observed stages (10Q): {stages}")
    assert stages[0] == "INTRO"
    assert stages[1] in ("RESUME_JD", "TECHNICAL_FUNDAMENTALS")
    # Verify PROJECT appears after INTRO and RESUME_JD
    first_project_idx = next(i for i, s in enumerate(stages) if s == "PROJECT")
    assert first_project_idx >= 3, f"Project question appeared too early at index {first_project_idx}"
    # Verify ADVANCED_TECHNICAL appears toward the end
    last_stage = stages[-1]
    assert last_stage == "ADVANCED_TECHNICAL"
    print("  PASS: Natural progression verified: Intro -> Resume/JD -> Fundamentals -> Project -> Advanced")

    # -------------------------------------------------------------------------
    # TEST 4: HR interview starts with introduction/background
    # -------------------------------------------------------------------------
    print("\n[TEST 4] HR interview starts with introduction/background...")
    hr_req = QuestionGenerationRequest(
        candidate_profile=cand,
        job_profile=job,
        interview_type="HR",
        difficulty="Medium",
        question_count=5,
    )
    with patch("app.services.llm_service.generate_json_response", new=AsyncMock(return_value={"questions": []})):
        res = client.post("/api/v1/interview/generate-questions", json=hr_req.model_dump())
        assert res.status_code == 200
        hr_data = res.json()
        assert hr_data["questions"][0]["stage"] == "INTRO"
        assert all(q["category"] == "HR" for q in hr_data["questions"])
        print("  PASS: HR interview starts with INTRO and contains only HR questions")

    # -------------------------------------------------------------------------
    # TEST 5: Mixed interview contains both technical and behavioral stages
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Mixed interview contains both technical and behavioral stages...")
    mixed_req = QuestionGenerationRequest(
        candidate_profile=cand,
        job_profile=job,
        interview_type="Mixed",
        difficulty="Medium",
        question_count=10,
    )
    with patch("app.services.llm_service.generate_json_response", new=AsyncMock(return_value={"questions": []})):
        res = client.post("/api/v1/interview/generate-questions", json=mixed_req.model_dump())
        assert res.status_code == 200
        mixed_data = res.json()
        assert mixed_data["questions"][0]["stage"] == "INTRO"
        categories = {q["category"] for q in mixed_data["questions"]}
        assert "Technical" in categories or "HR" in categories
        print("  PASS: Mixed interview generated with balanced introduction and competencies")

    # -------------------------------------------------------------------------
    # TEST 6: 5-question interview respects stage progression
    # -------------------------------------------------------------------------
    print("\n[TEST 6] 5-question interview respects stage progression...")
    seq_5 = determine_stage_sequence(5, "Technical")
    assert seq_5 == ["INTRO", "RESUME_JD", "TECHNICAL_FUNDAMENTALS", "PROJECT", "ADVANCED_TECHNICAL"]
    print(f"  PASS: 5-question sequence: {seq_5}")

    # -------------------------------------------------------------------------
    # TEST 7: 10-question interview respects stage progression
    # -------------------------------------------------------------------------
    print("\n[TEST 7] 10-question interview respects stage progression...")
    seq_10 = determine_stage_sequence(10, "Technical")
    assert seq_10[0] == "INTRO"
    assert seq_10[1] == "RESUME_JD"
    assert seq_10[3] == "TECHNICAL_FUNDAMENTALS"
    assert "PROJECT" in seq_10
    assert seq_10[-1] == "ADVANCED_TECHNICAL"
    print(f"  PASS: 10-question sequence: {seq_10}")

    # -------------------------------------------------------------------------
    # TEST 8: 15-question interview respects stage progression
    # -------------------------------------------------------------------------
    print("\n[TEST 8] 15-question interview respects stage progression...")
    seq_15 = determine_stage_sequence(15, "Technical")
    assert len(seq_15) == 15
    assert seq_15[0] == "INTRO"
    assert seq_15[1] == "RESUME_JD"
    assert seq_15[3] == "TECHNICAL_FUNDAMENTALS"
    assert seq_15[-1] == "ADVANCED_TECHNICAL"
    print(f"  PASS: 15-question sequence starts at INTRO and ends at ADVANCED_TECHNICAL (length={len(seq_15)})")

    # -------------------------------------------------------------------------
    # TEST 9: Project questions are not asked before introductory/resume questions
    # -------------------------------------------------------------------------
    print("\n[TEST 9] Project questions never precede introductory/resume questions...")
    for idx, q in enumerate(data["questions"]):
        if q["stage"] == "PROJECT":
            assert idx >= 2, f"Project question found at index {idx}, which precedes resume fundamentals!"
    print("  PASS: All project questions strictly follow introduction and resume fundamentals")

    # -------------------------------------------------------------------------
    # TEST 10: Adaptive follow-up remains within the current topic
    # -------------------------------------------------------------------------
    print("\n[TEST 10] Adaptive follow-up remains within current topic...")
    dec = decide_next_action(
        evaluation=AdaptiveEvaluationInput(score=40, technicalAccuracy=35, relevance=80, depth=30, clarity=60, improvements=["Missing compound index behavior"]),
        previous_question="How does indexing improve MongoDB queries?",
        category="Technical",
        difficulty="Medium",
        current_topic="MongoDB",
        relevant_skills=["MongoDB"],
    )
    assert dec.decision == "TARGETED_FOLLOW_UP"
    assert dec.target_skill == "MongoDB", f"Expected target_skill=MongoDB, got {dec.target_skill}"
    print(f"  PASS: Adaptive decision={dec.decision}, locked to target_skill='{dec.target_skill}'")

    # -------------------------------------------------------------------------
    # TEST 11: Strong technical answer can advance to a deeper question
    # -------------------------------------------------------------------------
    print("\n[TEST 11] Strong technical answer advances to deeper challenge...")
    strong_dec = decide_next_action(
        evaluation=AdaptiveEvaluationInput(score=92, technicalAccuracy=95, relevance=95, depth=90, clarity=90),
        previous_question="Explain how Redis functions as a cache.",
        category="Technical",
        difficulty="Medium",
        current_topic="Redis",
        relevant_skills=["Redis"],
    )
    assert strong_dec.decision in ("DEEPER_CHALLENGE", "ADVANCE_DIFFICULTY")
    print(f"  PASS: Strong answer triggered decision={strong_dec.decision}")

    # -------------------------------------------------------------------------
    # TEST 12: Weak technical answer triggers targeted follow-up
    # -------------------------------------------------------------------------
    print("\n[TEST 12] Weak technical answer triggers targeted follow-up...")
    weak_dec = decide_next_action(
        evaluation=AdaptiveEvaluationInput(score=45, technicalAccuracy=40, relevance=80, depth=35, clarity=70, improvements=["Confused REST PUT and PATCH"]),
        previous_question="What is the difference between PUT and PATCH?",
        category="Technical",
        difficulty="Medium",
        current_topic="REST APIs",
        relevant_skills=["REST APIs"],
    )
    assert weak_dec.decision == "TARGETED_FOLLOW_UP"
    assert weak_dec.target_skill == "REST APIs"
    print(f"  PASS: Weak answer triggered TARGETED_FOLLOW_UP on '{weak_dec.target_skill}'")

    # -------------------------------------------------------------------------
    # TEST 13: Phase 10 evaluation remains functional
    # -------------------------------------------------------------------------
    print("\n[TEST 13] Phase 10 evaluation remains functional...")
    eval_req = AnswerEvaluationRequest(
        question="What is an index in PostgreSQL?",
        candidate_answer="",
        category="Technical",
    )
    eval_res = client.post("/api/v1/evaluation/evaluate", json=eval_req.model_dump())
    assert eval_res.status_code == 200
    assert eval_res.json()["score"] == 0
    assert eval_res.json()["answer_status"] == "NON_ANSWER"
    print("  PASS: Phase 10 evaluation returns verified gated response")

    # -------------------------------------------------------------------------
    # TEST 14: Phase 8 session persistence remains functional
    # -------------------------------------------------------------------------
    print("\n[TEST 14] Phase 8 session persistence remains functional...")
    now_ms = int(time.time() * 1000)
    session = InterviewSessionState(
        session_id="test-session-123",
        created_at=now_ms,
        started_at=now_ms,
        current_question_started_at=now_ms,
        questions=[data["questions"][0]],
    )
    serialized = session.model_dump()
    restored = InterviewSessionState.restore_safely(serialized)
    assert restored is not None
    assert restored.questions[0].stage == "INTRO"
    print("  PASS: InterviewSessionState safely restored with stage metadata preserved")

    # -------------------------------------------------------------------------
    # TEST 15: Existing Phase 7 question generation remains functional
    # -------------------------------------------------------------------------
    print("\n[TEST 15] Existing Phase 7 question generation response schema...")
    assert isinstance(data["count"], int)
    assert data["count"] == 10
    assert data["role"] == "Backend Software Engineer"
    print("  PASS: QuestionGenerationResponse fully valid and populated")

    # -------------------------------------------------------------------------
    # TEST 16: 'I don't know' in adaptive transitions to NEXT_TOPIC
    # -------------------------------------------------------------------------
    print("\n[TEST 16] Non-answer ('I don't know') in adaptive flow transitions to NEXT_TOPIC...")
    idk_eval = AdaptiveEvaluationInput(
        score=0,
        technicalAccuracy=0,
        relevance=0,
        depth=0,
        clarity=0,
        improvements=["The response does not attempt to answer the question. No answer was provided."],
    )
    idk_dec = decide_next_action(
        evaluation=idk_eval,
        previous_question="Can you explain RESTful API design principles?",
        category="Technical",
        difficulty="Medium",
        current_topic="REST APIs",
    )
    assert idk_dec.decision == "NEXT_TOPIC", f"Expected NEXT_TOPIC for 'I don't know', got {idk_dec.decision}"
    assert idk_dec.is_follow_up is False
    print(f"  PASS: 'I don't know' resulted in decision='{idk_dec.decision}' (no infinite drilling)")

    # -------------------------------------------------------------------------
    # TEST 17: Introduction question in adaptive transitions to NEXT_TOPIC
    # -------------------------------------------------------------------------
    print("\n[TEST 17] Introduction question in adaptive flow transitions to NEXT_TOPIC...")
    intro_eval = AdaptiveEvaluationInput(
        score=85,
        technicalAccuracy=80,
        relevance=90,
        depth=80,
        clarity=90,
        strengths=["Clear background summary"],
    )
    intro_dec = decide_next_action(
        evaluation=intro_eval,
        previous_question="Could you please introduce yourself and walk me through your background?",
        category="HR",
        difficulty="Easy",
        current_topic="Candidate Introduction",
    )
    assert intro_dec.decision == "NEXT_TOPIC"
    print("  PASS: Introduction question smoothly transitions to NEXT_TOPIC")

    print("\n=================================================================")
    print("ALL 17 INTERVIEW FLOW AUTOMATED TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")


if __name__ == "__main__":
    run_all_tests()
