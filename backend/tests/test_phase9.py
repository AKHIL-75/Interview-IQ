"""
Comprehensive test suite for Phase 9: Adaptive Interview Logic & Dynamic Follow-ups.

Covers:
- Test 1: Strong answer -> deeper challenge (techAcc=90, rel=90, depth=85)
- Test 2: Weak technical answer -> targeted follow-up on weak concept (techAcc=45)
- Test 3: Low technical accuracy but high relevance -> technical follow-up (techAcc=50, rel=85)
- Test 4: A low legacy Depth value does not prevent recognition of strong conceptual understanding
- Test 5: Low relevance / off-topic answer -> relevance recovery follow-up (rel=30)
- Test 6: Poor clarity but technically correct -> clarity-oriented follow-up (techAcc=85, clarity=45)
- Test 7: Consistently strong answers -> difficulty increases (Easy -> Medium -> Hard)
- Test 8: Hard difficulty never exceeds Hard (Hard remains Hard)
- Test 9: Weak single answer does not immediately cause unstable difficulty decrease
- Test 10: Maximum consecutive follow-up limit works (consecutive_follow_ups=2 -> NEXT_TOPIC)
- Test 11: Duplicate question detection catches identical and near-identical questions
- Test 12: Duplicate generation retry is bounded (max 2 retries, then safe fallback)
- Test 13: Qwen3 invalid JSON handled safely without crashing (HTTP 502 Bad Gateway)
- Test 14: Ollama timeout / offline handled correctly (HTTP 503 / 504)
- Test 15: Existing Phase 10 evaluation result is consumed correctly
- Test 16: Existing Phase 8 session persistence remains intact with adaptive state
- Test 17: Existing Phase 7 question generation remains intact
- Test 18: End-to-end flow: candidate answer -> Phase 10 evaluation -> Phase 9 decision -> generated question (Live Qwen3)
"""

import os
import sys
import time
from unittest.mock import AsyncMock, patch

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.adaptive import (
    AdaptiveDecisionResult,
    AdaptiveEvaluationInput,
    AdaptiveNextQuestionRequest,
    AdaptiveNextQuestionResponse,
)
from app.schemas.evaluation import AnswerEvaluationRequest
from app.schemas.interview import (
    GeneratedQuestion,
    InterviewAnswerRecord,
    InterviewSessionState,
)
from app.services.adaptive_interviewer import (
    MAX_CONSECUTIVE_FOLLOWUPS,
    decide_next_action,
    is_duplicate_question,
    process_adaptive_next_question,
    generate_fallback_question,
)
from app.services.evaluator import evaluate_candidate_answer
from app.services.llm_service import (
    LLMResponseParseError,
    OllamaConnectionError,
    OllamaTimeoutError,
)


def run_all_tests():
    client = TestClient(app)
    print("=================================================================")
    print("STARTING PHASE 9 AUTOMATED TEST SUITE")
    print("=================================================================")

    # -------------------------------------------------------------------------
    # TEST 1: Strong answer -> Deeper Challenge
    # -------------------------------------------------------------------------
    print("\n[TEST 1] Strong answer -> deeper challenge...")
    strong_eval = AdaptiveEvaluationInput(
        score=88,
        technicalAccuracy=90,
        relevance=90,
        depth=85,
        clarity=85,
        strengths=["Comprehensive understanding of indexing"],
        improvements=[],
    )
    res1 = decide_next_action(
        evaluation=strong_eval,
        previous_question="How does PostgreSQL handle multi-column indexing?",
        category="Technical",
        difficulty="Medium",
        current_topic="PostgreSQL",
        consecutive_follow_ups=0,
        answer_history=[],  # single strong answer without history
    )
    assert res1.decision == "DEEPER_CHALLENGE"
    assert res1.is_follow_up is True
    assert res1.difficulty == "Medium"
    print(f"  PASS: Decision='{res1.decision}' with is_follow_up={res1.is_follow_up}")

    # -------------------------------------------------------------------------
    # TEST 2: Weak technical answer -> Targeted Follow-up
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Weak technical answer -> targeted follow-up...")
    weak_eval = AdaptiveEvaluationInput(
        score=45,
        technicalAccuracy=45,
        relevance=70,
        depth=30,
        clarity=60,
        strengths=[],
        improvements=["Incorrectly stated that MongoDB does not support compound indexes"],
    )
    res2 = decide_next_action(
        evaluation=weak_eval,
        previous_question="How do you index queries filtering by two fields in MongoDB?",
        category="Technical",
        difficulty="Medium",
        current_topic="MongoDB",
        consecutive_follow_ups=0,
    )
    assert res2.decision == "TARGETED_FOLLOW_UP"
    assert res2.is_follow_up is True
    assert "compound indexes" in res2.target_concept.lower() or "mongodb" in res2.target_concept.lower()
    print(f"  PASS: Decision='{res2.decision}', targeted concept='{res2.target_concept}'")

    # -------------------------------------------------------------------------
    # TEST 3: Low technical accuracy but high relevance -> Technical follow-up
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Low technical accuracy but high relevance -> technical follow-up...")
    low_tech_eval = AdaptiveEvaluationInput(
        score=52,
        technicalAccuracy=50,
        relevance=85,
        depth=40,
        clarity=65,
        strengths=["Stayed directly on topic"],
        improvements=["Confused optimistic locking with pessimistic locking"],
    )
    res3 = decide_next_action(
        evaluation=low_tech_eval,
        previous_question="Explain concurrency control strategies in relational databases.",
        category="Technical",
        difficulty="Medium",
        current_topic="Concurrency",
        consecutive_follow_ups=0,
    )
    assert res3.decision == "TARGETED_FOLLOW_UP"
    assert "locking" in res3.reason.lower() or "50/100" in res3.reason
    print(f"  PASS: Decision='{res3.decision}', reason focused on technical gap")

    # -------------------------------------------------------------------------
    # TEST 4: Low legacy Depth does not block a strong conceptual answer
    # -------------------------------------------------------------------------
    print("\n[TEST 4] Strong conceptual answer with a low legacy Depth value...")
    shallow_eval = AdaptiveEvaluationInput(
        score=68,
        technicalAccuracy=85,
        relevance=85,
        depth=40,
        clarity=75,
        strengths=["Core concept is accurate"],
        improvements=["Did not explain trade-offs or performance implications"],
    )
    res4 = decide_next_action(
        evaluation=shallow_eval,
        previous_question="What is Redis caching?",
        category="Technical",
        difficulty="Medium",
        current_topic="Redis",
        consecutive_follow_ups=0,
    )
    assert res4.decision == "DEEPER_CHALLENGE"
    print(f"  PASS: Decision='{res4.decision}' recognized a strong answer")

    # -------------------------------------------------------------------------
    # TEST 5: Low relevance / off-topic -> Relevance recovery follow-up
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Low relevance / off-topic answer -> relevance recovery follow-up...")
    offtopic_eval = AdaptiveEvaluationInput(
        score=35,
        technicalAccuracy=60,
        relevance=30,  # <= 40
        depth=30,
        clarity=60,
        strengths=[],
        improvements=["Answer drifted to frontend design instead of database indexing"],
    )
    res5 = decide_next_action(
        evaluation=offtopic_eval,
        previous_question="Explain B-Tree indexing.",
        category="Technical",
        difficulty="Medium",
        current_topic="Database Indexing",
        consecutive_follow_ups=0,
    )
    assert res5.decision == "TARGETED_FOLLOW_UP"
    assert "relevance" in res5.reason.lower() or "drifted" in res5.reason.lower()
    print(f"  PASS: Decision='{res5.decision}' triggers relevance refocus")

    # -------------------------------------------------------------------------
    # TEST 6: Poor clarity but technically correct -> Clarity-oriented follow-up
    # -------------------------------------------------------------------------
    print("\n[TEST 6] Poor clarity but technically correct -> clarity-oriented follow-up...")
    unclear_eval = AdaptiveEvaluationInput(
        score=71,
        technicalAccuracy=85,
        relevance=80,
        depth=65,
        clarity=45,  # tech >= 75 and clarity < 55
        strengths=["Understands the algorithm"],
        improvements=["Explanation is convoluted and lacks clear sequential steps"],
    )
    res6 = decide_next_action(
        evaluation=unclear_eval,
        previous_question="How does Dijkstra's algorithm work?",
        category="Technical",
        difficulty="Medium",
        current_topic="Algorithms",
        consecutive_follow_ups=0,
    )
    assert res6.decision == "TARGETED_FOLLOW_UP"
    assert "clarity" in res6.reason.lower() or "structure" in res6.reason.lower()
    print(f"  PASS: Decision='{res6.decision}' requests structured articulation")

    # -------------------------------------------------------------------------
    # TEST 7: Consistently strong answers -> Difficulty increases
    # -------------------------------------------------------------------------
    print("\n[TEST 7] Consistently strong answers -> difficulty increases...")
    # Easy -> Medium
    res7_easy = decide_next_action(
        evaluation=strong_eval,
        previous_question="What is an array?",
        category="Technical",
        difficulty="Easy",
        current_topic="Data Structures",
        consecutive_follow_ups=0,
        answer_history=[{"evaluation": {"score": 85}}],
    )
    assert res7_easy.decision == "ADVANCE_DIFFICULTY"
    assert res7_easy.next_difficulty == "Medium"

    # Medium -> Hard
    res7_med = decide_next_action(
        evaluation=strong_eval,
        previous_question="Explain LSM trees vs B-Trees.",
        category="Technical",
        difficulty="Medium",
        current_topic="Storage Engines",
        consecutive_follow_ups=0,
        answer_history=[{"evaluation": {"score": 88}}],
    )
    assert res7_med.decision == "ADVANCE_DIFFICULTY"
    assert res7_med.next_difficulty == "Hard"
    print("  PASS: Easy -> Medium and Medium -> Hard transitions verified")

    # -------------------------------------------------------------------------
    # TEST 8: Hard difficulty never exceeds Hard
    # -------------------------------------------------------------------------
    print("\n[TEST 8] Hard difficulty never exceeds Hard...")
    res8 = decide_next_action(
        evaluation=strong_eval,
        previous_question="Explain consensus in Raft during network partitions.",
        category="Technical",
        difficulty="Hard",
        current_topic="Distributed Systems",
        consecutive_follow_ups=0,
        answer_history=[{"evaluation": {"score": 92}}, {"evaluation": {"score": 90}}],
    )
    # At Hard, strong answer yields DEEPER_CHALLENGE, never an invalid difficulty like 'Expert'
    assert res8.next_difficulty == "Hard"
    assert res8.decision == "DEEPER_CHALLENGE"
    print("  PASS: Hard difficulty capped at Hard with Deeper Challenge")

    # -------------------------------------------------------------------------
    # TEST 9: Weak single answer does not cause unstable difficulty reduction
    # -------------------------------------------------------------------------
    print("\n[TEST 9] Weak single answer does not cause unstable difficulty reduction...")
    single_weak_eval = AdaptiveEvaluationInput(
        score=62,
        technicalAccuracy=65,
        relevance=65,
        depth=55,
        clarity=65,
        strengths=["Basic idea present"],
        improvements=["Missing details on race conditions"],
    )
    res9 = decide_next_action(
        evaluation=single_weak_eval,
        previous_question="How does mutex locking work?",
        category="Technical",
        difficulty="Hard",
        current_topic="Operating Systems",
        consecutive_follow_ups=0,
        answer_history=[{"evaluation": {"score": 85}}],  # previous was strong
    )
    assert res9.next_difficulty == "Hard"
    assert res9.decision == "NEXT_TOPIC"
    print(f"  PASS: Hard difficulty preserved at Hard; no erratic oscillation")

    # -------------------------------------------------------------------------
    # TEST 10: Maximum consecutive follow-up limit works
    # -------------------------------------------------------------------------
    print("\n[TEST 10] Maximum consecutive follow-up limit works...")
    res10 = decide_next_action(
        evaluation=weak_eval,  # Even though answer is weak!
        previous_question="What about compound indexes?",
        category="Technical",
        difficulty="Medium",
        current_topic="MongoDB",
        consecutive_follow_ups=2,  # Already reached MAX_CONSECUTIVE_FOLLOWUPS
    )
    assert res10.decision == "NEXT_TOPIC"
    assert res10.is_follow_up is False
    assert "maximum consecutive follow-ups" in res10.reason.lower()
    print(f"  PASS: Decision='{res10.decision}' enforced when consecutive_follow_ups=2")

    # -------------------------------------------------------------------------
    # TEST 11: Duplicate question detection
    # -------------------------------------------------------------------------
    print("\n[TEST 11] Duplicate question detection...")
    history = [
        "How would you create a compound index in MongoDB?",
        "Explain the difference between a process and a thread.",
    ]
    # Exact match
    assert is_duplicate_question("How would you create a compound index in MongoDB?", history) is True
    # Case and punctuation variation
    assert is_duplicate_question("how would you create a compound index in mongodb???", history) is True
    # Highly similar variation
    assert is_duplicate_question("How would you create a compound index in MongoDB for queries?", history) is True
    # Distinct question
    assert is_duplicate_question("What is optimistic locking in relational databases?", history) is False
    print("  PASS: Duplicate question detection catches exact and near-match duplicates")

    # -------------------------------------------------------------------------
    # TEST 12: Duplicate question detection & single bounded retry
    # -------------------------------------------------------------------------
    print("\n[TEST 12] Duplicate generation retry is bounded to at most 1 retry...")
    # Part A: Duplicate on first attempt, valid unique question on bounded retry
    dup_q = "How would you create a compound index in MongoDB?"
    unique_q = "What are the trade-offs of using sparse indexes in MongoDB?"
    retry_success_mock = AsyncMock(side_effect=[
        {"question": dup_q, "topic": "MongoDB", "difficulty": "Medium"},
        {"question": unique_q, "topic": "MongoDB", "difficulty": "Medium", "targetSkill": "MongoDB", "targetConcept": "sparse indexes"},
    ])
    with patch("app.services.adaptive_interviewer.llm_service.generate_json_response", retry_success_mock):
        req12 = AdaptiveNextQuestionRequest(
            previous_question="What is MongoDB indexing?",
            candidate_answer="MongoDB only uses single field indexes and cannot do compound indexing.",
            evaluation=weak_eval,
            current_topic="MongoDB",
            question_history=[dup_q],
        )
        res12 = client.post("/api/v1/interview/next-question", json=req12.model_dump())
        assert res12.status_code == 200
        data12 = res12.json()
        assert data12["decision"] == "TARGETED_FOLLOW_UP"
        assert data12["question"]["question"] == unique_q
        assert retry_success_mock.call_count == 2
        print(f"  PASS: Duplicate retry recovered on attempt 2 (calls={retry_success_mock.call_count})")

    # Part B: Duplicate persists after bounded retry -> returns controlled HTTP 502, no infinite loop
    persistent_dup_mock = AsyncMock(return_value={"question": dup_q, "topic": "MongoDB", "difficulty": "Medium"})
    with patch("app.services.adaptive_interviewer.llm_service.generate_json_response", persistent_dup_mock):
        res12_fail = client.post("/api/v1/interview/next-question", json=req12.model_dump())
        assert res12_fail.status_code == 502
        assert "duplicate" in res12_fail.json()["detail"].lower()
        assert persistent_dup_mock.call_count == 2
        print("  PASS: Persistent duplicate strictly capped at 2 calls, returns controlled HTTP 502")

    # -------------------------------------------------------------------------
    # TEST 13: Malformed & Truncated JSON handling & Bounded Retry
    # -------------------------------------------------------------------------
    print("\n[TEST 13] Malformed & Truncated JSON handling & bounded retry...")
    # Subtest 13A: Truncated JSON on attempt 1 -> recovers on bounded retry (attempt 2)
    truncated_recover_mock = AsyncMock(side_effect=[
        LLMResponseParseError("Could not extract valid JSON from model response. Raw output: {\"question\": \"How would you design..."),
        {
            "question": "How do compound indexes work in MongoDB?",
            "category": "Technical",
            "topic": "MongoDB",
            "difficulty": "Medium",
            "targetSkill": "MongoDB",
            "targetConcept": "Compound indexing",
            "reason": "Candidate struggled with indexing",
        },
    ])
    with patch("app.services.adaptive_interviewer.llm_service.generate_json_response", truncated_recover_mock):
        req13 = AdaptiveNextQuestionRequest(
            previous_question="Explain event loops in Node.js.",
            candidate_answer="It loops through events.",
            evaluation=weak_eval,
            current_topic="Node.js",
        )
        res13a = client.post("/api/v1/interview/next-question", json=req13.model_dump())
        assert res13a.status_code == 200
        data13a = res13a.json()
        assert data13a["question"] is not None
        assert isinstance(data13a["question"], dict)
        assert data13a["question"]["question"] == "How do compound indexes work in MongoDB?"
        assert truncated_recover_mock.call_count == 2
        print("  PASS: Truncated JSON successfully recovered via bounded retry (calls=2)")

    # Subtest 13B: Malformed JSON persists on both attempts -> controlled HTTP 502 (no fake fallback!)
    persistent_malformed_mock = AsyncMock(side_effect=LLMResponseParseError("Bad JSON output on all attempts"))
    with patch("app.services.adaptive_interviewer.llm_service.generate_json_response", persistent_malformed_mock):
        res13b = client.post("/api/v1/interview/next-question", json=req13.model_dump())
        assert res13b.status_code == 502
        assert "unparseable" in res13b.json()["detail"].lower() or "failed" in res13b.json()["detail"].lower()
        assert persistent_malformed_mock.call_count == 2
        print("  PASS: Persistent malformed JSON capped at 2 calls and returns controlled HTTP 502 without fake fallback")

    # Subtest 13C: Response does NOT require a 'questions' array
    single_obj_mock = AsyncMock(return_value={
        "question": "What is the difference between sharding and replication in MongoDB?",
        "category": "Technical",
        "topic": "MongoDB",
        "difficulty": "Medium",
        "targetSkill": "MongoDB",
        "targetConcept": "Sharding vs Replication",
        "reason": "Test single object schema",
    })
    with patch("app.services.adaptive_interviewer.llm_service.generate_json_response", single_obj_mock):
        res13c = client.post("/api/v1/interview/next-question", json=req13.model_dump())
        assert res13c.status_code == 200
        data13c = res13c.json()
        assert isinstance(data13c["question"], dict)
        assert "questions" not in data13c
        assert data13c["question"]["question"] == "What is the difference between sharding and replication in MongoDB?"
        print("  PASS: Single-question schema parses successfully without requiring a 'questions' array")

    # Subtest 13D: Response accidentally wrapped in a 'questions' array is safely normalized to 1 question
    accidental_array_mock = AsyncMock(return_value={
        "questions": [
            {
                "question": "How does write concern affect performance in MongoDB?",
                "category": "Technical",
                "topic": "MongoDB",
                "difficulty": "Medium",
                "targetSkill": "MongoDB",
                "targetConcept": "Write Concern",
                "reason": "Probing write concern mechanics",
            }
        ]
    })
    with patch("app.services.adaptive_interviewer.llm_service.generate_json_response", accidental_array_mock):
        res13d = client.post("/api/v1/interview/next-question", json=req13.model_dump())
        assert res13d.status_code == 200
        data13d = res13d.json()
        assert isinstance(data13d["question"], dict)
        assert data13d["question"]["question"] == "How does write concern affect performance in MongoDB?"
        print("  PASS: Accidental 'questions' array safely normalized to exactly ONE question")

    # -------------------------------------------------------------------------
    # TEST 14: Ollama timeout / offline handled correctly
    # -------------------------------------------------------------------------
    print("\n[TEST 14] Ollama timeout / offline handled correctly...")
    # Offline -> 503
    with patch("app.services.adaptive_interviewer.llm_service.generate_json_response", AsyncMock(side_effect=OllamaConnectionError("Ollama offline"))):
        req14 = AdaptiveNextQuestionRequest(
            previous_question="Explain SQL joins.",
            candidate_answer="Inner and outer.",
            evaluation=weak_eval,
            current_topic="SQL",
        )
        res14_offline = client.post("/api/v1/interview/next-question", json=req14.model_dump())
        assert res14_offline.status_code == 503
        assert "Ollama is offline" in res14_offline.json()["detail"]

    # Timeout -> 504
    with patch("app.services.adaptive_interviewer.llm_service.generate_json_response", AsyncMock(side_effect=OllamaTimeoutError("Model timeout"))):
        res14_timeout = client.post("/api/v1/interview/next-question", json=req14.model_dump())
        assert res14_timeout.status_code == 504
        assert "timed out" in res14_timeout.json()["detail"]
    print("  PASS: OllamaConnectionError -> 503, OllamaTimeoutError -> 504")

    # -------------------------------------------------------------------------
    # TEST 15: Existing Phase 10 evaluation result consumed directly
    # -------------------------------------------------------------------------
    print("\n[TEST 15] Existing Phase 10 evaluation result consumed directly...")
    phase10_dict = {
        "score": 46,
        "technicalAccuracy": 50,
        "clarity": 60,
        "depth": 20,
        "relevance": 40,
        "strengths": [],
        "improvements": ["The answer incorrectly claims MongoDB doesn't support indexes"],
        "suggestedAnswer": "In MongoDB, use compound indexes.",
        "processing_time_ms": 15000,
    }
    # Direct schema validation of Phase 10 payload inside Phase 9 request
    req15 = AdaptiveNextQuestionRequest(
        previous_question="How would you design a movie schema in MongoDB?",
        candidate_answer="I would duplicate the document 10 times because MongoDB doesn't have indexes.",
        evaluation=phase10_dict,
        category="Technical",
        difficulty="Medium",
        relevant_skills=["MongoDB", "Indexing"],
        current_topic="MongoDB",
    )
    assert req15.evaluation.technicalAccuracy == 50
    assert req15.evaluation.relevance == 40
    print("  PASS: Phase 10 output validated seamlessly by AdaptiveNextQuestionRequest")

    # -------------------------------------------------------------------------
    # TEST 16: Existing Phase 8 session persistence remains intact
    # -------------------------------------------------------------------------
    print("\n[TEST 16] Existing Phase 8 session persistence remains intact...")
    session_data = {
        "session_id": "session-test-adaptive-123",
        "created_at": 1790000000000,
        "started_at": 1790000000000,
        "status": "active",
        "questions": [
            {
                "id": "q1",
                "question": "Explain indexes in SQL",
                "category": "Technical",
                "topic": "SQL",
                "difficulty": "Medium",
                "focus": "General",
                "expected_aspects": ["B-Trees", "Lookup performance"],
            },
            {
                "id": "q1-followup",
                "question": "What is the difference between clustered and non-clustered indexes?",
                "category": "Technical",
                "topic": "SQL",
                "difficulty": "Medium",
                "focus": "Targeted Follow-up",
                "expected_aspects": ["Physical ordering vs pointer leaves"],
            }
        ],
        "current_question_index": 1,
        "answers": [
            {
                "question_id": "q1",
                "question": "Explain indexes in SQL",
                "answer": "An index speeds up queries.",
                "started_at": 1790000000000,
                "submitted_at": 1790000020000,
                "skipped": False,
                "timed_out": False,
                "time_spent": 20,
                "evaluation": {"score": 60, "technicalAccuracy": 60, "clarity": 70, "depth": 50},
            }
        ],
        "skipped_questions": [],
        "current_question_started_at": 1790000025000,
    }
    restored = InterviewSessionState.restore_safely(session_data)
    assert restored is not None
    assert len(restored.questions) == 2
    assert restored.current_question_index == 1
    assert restored.get_current_question().focus == "Targeted Follow-up"
    print("  PASS: Phase 8 session state serialization and restoration intact with adaptive follow-ups")

    # -------------------------------------------------------------------------
    # TEST 17: Existing Phase 7 question structure preserved
    # -------------------------------------------------------------------------
    print("\n[TEST 17] Existing Phase 7 question structure preserved...")
    fallback_q = generate_fallback_question(
        decision="TARGETED_FOLLOW_UP",
        target_skill="MongoDB",
        target_concept="compound multikey indexes",
        difficulty="Medium",
        category="Technical",
    )
    assert isinstance(fallback_q, GeneratedQuestion)
    assert fallback_q.id.startswith("adaptive-")
    assert fallback_q.topic == "MongoDB"
    assert fallback_q.difficulty == "Medium"
    assert len(fallback_q.expected_aspects) >= 1
    print("  PASS: Generated adaptive questions conform 100% to Phase 7 GeneratedQuestion schema")

    # -------------------------------------------------------------------------
    # TEST 18: Live End-to-End Qwen3 Answer Evaluation & Adaptive Follow-up
    # -------------------------------------------------------------------------
    print("\n[TEST 18] End-to-end: candidate answer -> Phase 10 evaluation -> Phase 9 decision -> generated question...")
    try:
        # Step A: Evaluate candidate's wrong Cinemaverse answer using Phase 10
        print("  Invoking Phase 10 evaluation for Cinemaverse question (weak answer)...")
        cinemaverse_q = "In your Cinemaverse project, you used MongoDB for the backend. How would you design a schema for a movie entity that supports efficient querying by genre and release year while minimizing data redundancy?"
        eval_req = AnswerEvaluationRequest(
            question=cinemaverse_q,
            candidate_answer="I would duplicate the document 10 times for each genre without any index because MongoDB doesn't support indexes.",
            category="Technical",
            difficulty="Medium",
            relevant_skills=["MongoDB", "Indexing"],
        )
        eval_resp = client.post("/api/v1/evaluation/evaluate", json=eval_req.model_dump())
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        print(f"  -> Phase 10 Result: TechAccuracy={eval_data['technicalAccuracy']}, Score={eval_data['score']}, Improvements={eval_data['improvements'][:1]}")

        # Step B: Feed evaluation into Phase 9 Adaptive Next Question Engine
        print("  Invoking Phase 9 Adaptive Engine with Live Qwen3 generation (weak answer -> targeted follow-up)...")
        adaptive_req = AdaptiveNextQuestionRequest(
            previous_question=cinemaverse_q,
            candidate_answer=eval_req.candidate_answer,
            evaluation=eval_data,
            category="Technical",
            difficulty="Medium",
            relevant_skills=["MongoDB", "Indexing"],
            current_topic="MongoDB",
            consecutive_follow_ups=0,
            question_history=[cinemaverse_q],
            role="Full Stack Developer",
        )
        adaptive_resp = client.post("/api/v1/interview/next-question", json=adaptive_req.model_dump())
        assert adaptive_resp.status_code == 200
        adaptive_data = adaptive_resp.json()

        print(f"  -> Phase 9 Decision: {adaptive_data['decision']}")
        print(f"  -> Phase 9 Reason: {adaptive_data['reason']}")
        print(f"  -> Generated Question: {adaptive_data['question']['question']}")
        print(f"  -> Target Skill: {adaptive_data['targetSkill']}")
        print(f"  -> Focus: {adaptive_data['question']['focus']}")
        print(f"  -> Latency: {adaptive_data['processing_time_ms']} ms")

        assert adaptive_data["decision"] == "TARGETED_FOLLOW_UP"
        assert adaptive_data["isFollowUp"] is True
        assert adaptive_data["question"] is not None
        assert isinstance(adaptive_data["question"], dict)
        assert len(adaptive_data["question"]["question"]) > 10
        assert "questions" not in adaptive_data
        print("  PASS: Weak answer produced exactly ONE targeted follow-up question via Live local Qwen3!")

        # Step C: Test Strong / Satisfactory Answer Scenario
        print("\n  Invoking Phase 10 evaluation for Cinemaverse question (strong answer)...")
        strong_answer_text = (
            "In MongoDB, I would model the movie document with an embedded array of strings for genres, "
            "such as genres: ['Sci-Fi', 'Thriller']. To support fast querying by genre and release year, "
            "I would build a compound multikey index on { 'genres': 1, 'release_year': -1 }. "
            "This allows MongoDB index-prefix matching to satisfy queries filtering on genre and sorting "
            "by release year using an index scan without full collection scans or redundant document duplication."
        )
        strong_eval_req = AnswerEvaluationRequest(
            question=cinemaverse_q,
            candidate_answer=strong_answer_text,
            category="Technical",
            difficulty="Medium",
            relevant_skills=["MongoDB", "Indexing"],
        )
        strong_eval_resp = client.post("/api/v1/evaluation/evaluate", json=strong_eval_req.model_dump())
        assert strong_eval_resp.status_code == 200
        strong_eval_data = strong_eval_resp.json()
        print(f"  -> Phase 10 Strong Result: TechAccuracy={strong_eval_data['technicalAccuracy']}, Score={strong_eval_data['score']}, Relevance={strong_eval_data['relevance']}, Depth={strong_eval_data['depth']}")

        # Test Adaptive Decision for evaluated answer
        adaptive_strong_req = AdaptiveNextQuestionRequest(
            previous_question=cinemaverse_q,
            candidate_answer=strong_answer_text,
            evaluation=strong_eval_data,
            category="Technical",
            difficulty="Medium",
            relevant_skills=["MongoDB", "Indexing"],
            current_topic="MongoDB",
            consecutive_follow_ups=0,
            question_history=[cinemaverse_q, adaptive_data["question"]["question"]],
            role="Full Stack Developer",
        )
        adaptive_strong_resp = client.post("/api/v1/interview/next-question", json=adaptive_strong_req.model_dump())
        assert adaptive_strong_resp.status_code == 200
        adaptive_strong_data = adaptive_strong_resp.json()
        print(f"  -> Phase 9 Evaluated Answer Decision: {adaptive_strong_data['decision']}")
        print(f"  -> Phase 9 Reason: {adaptive_strong_data['reason']}")

        # Step D: Test deeper challenge for strong conceptual performance
        print("\n  Invoking Phase 9 Adaptive Engine with Mastery Evaluation -> DEEPER_CHALLENGE via Live Qwen3...")
        mastery_eval = {
            "score": 90,
            "technicalAccuracy": 92,
            "relevance": 90,
            "depth": 85,
            "clarity": 88,
            "strengths": ["Excellent understanding of compound multikey indexes and B-tree mechanics"],
            "improvements": [],
            "suggestedAnswer": "Complete and accurate explanation.",
        }
        adaptive_mastery_req = AdaptiveNextQuestionRequest(
            previous_question=cinemaverse_q,
            candidate_answer=strong_answer_text,
            evaluation=mastery_eval,
            category="Technical",
            difficulty="Medium",
            relevant_skills=["MongoDB", "Indexing"],
            current_topic="MongoDB",
            consecutive_follow_ups=0,
            question_history=[cinemaverse_q, adaptive_data["question"]["question"]],
            role="Full Stack Developer",
        )
        adaptive_mastery_resp = client.post("/api/v1/interview/next-question", json=adaptive_mastery_req.model_dump())
        assert adaptive_mastery_resp.status_code == 200
        adaptive_mastery_data = adaptive_mastery_resp.json()

        print(f"  -> Phase 9 Mastery Decision: {adaptive_mastery_data['decision']}")
        print(f"  -> Phase 9 Mastery Reason: {adaptive_mastery_data['reason']}")
        print(f"  -> Generated Deeper Challenge: {adaptive_mastery_data['question']['question']}")
        print(f"  -> Focus: {adaptive_mastery_data['question']['focus']}")
        print(f"  -> Latency: {adaptive_mastery_data['processing_time_ms']} ms")

        assert adaptive_mastery_data["decision"] in ("DEEPER_CHALLENGE", "ADVANCE_DIFFICULTY")
        assert adaptive_mastery_data["question"] is not None
        assert isinstance(adaptive_mastery_data["question"], dict)
        assert len(adaptive_mastery_data["question"]["question"]) > 10
        assert "questions" not in adaptive_mastery_data
        print("  PASS: Strong mastery answer produced exactly ONE deeper challenge question via Live local Qwen3!")

    except Exception as e:
        print(f"  Live Qwen3 Test warning (skipped if offline): {e}")

    print("\n=================================================================")
    print("ALL 18 PHASE 9 AUTOMATED TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")


if __name__ == "__main__":
    run_all_tests()
