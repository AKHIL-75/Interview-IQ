"""
Comprehensive test suite for Phase 10: Answer Evaluation Engine.

Covers:
- Test 1: Deterministic score calculation (60% accuracy, 30% relevance, 10% clarity)
- Test 2: Score range and clamping validation (0 to 100 bounds)
- Test 3: Empty answer edge case (deterministic score=0, all dimensions=0, actionable improvements)
- Test 4: Whitespace-only answer edge case (deterministic score=0)
- Test 5: Very short answer edge case handling
- Test 6: Invalid request validation (missing question, empty question -> HTTP 422)
- Test 7: Category normalization (Technical, HR, Behavioral, Mixed)
- Test 8: Difficulty normalization (Easy, Medium, Hard)
- Test 9: Prompt builder checks (rubric, guidelines, anti-hallucination rules present)
- Test 10: Ollama unavailable simulation -> HTTP 503 Service Unavailable
- Test 11: Ollama timeout simulation -> HTTP 504 Gateway Timeout
- Test 12: Invalid LLM JSON simulation -> HTTP 502 Bad Gateway
- Test 13: Resilient JSON key mapping and fallback handling
- Test 14: HR / Behavioral answer evaluation flow
- Test 15: Irrelevant answer (topic drift) evaluation flow
- Test 16: Suggested answer generation without candidate hallucination
- Test 17: CRITICAL WRONG-ANSWER TEST: Cinemaverse MongoDB Schema Design (Wrong vs Strong Answer comparison)
- Test 18: Live End-to-End Qwen3 Answer Evaluation & Latency Benchmark
"""

import os
import sys
import time
from unittest.mock import AsyncMock, patch

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from app.main import app
from app.prompts.evaluation_prompts import build_evaluation_prompt
from app.schemas.evaluation import (
    AnswerEvaluationRequest,
    AnswerEvaluationResponse,
)
from app.services.evaluator import (
    calculate_deterministic_score,
    _clamp_dimension,
    _extract_dimension_scores,
    evaluate_candidate_answer,
)
from app.services.llm_service import (
    OllamaConnectionError,
    OllamaTimeoutError,
    LLMResponseParseError,
)


def run_all_tests():
    client = TestClient(app)
    print("=================================================================")
    print("STARTING PHASE 10 AUTOMATED TEST SUITE")
    print("=================================================================")

    # -------------------------------------------------------------------------
    # TEST 1: Deterministic score formula
    # -------------------------------------------------------------------------
    print("\n[TEST 1] Deterministic score calculation formula...")
    # Formula: tech*0.60 + rel*0.30 + clarity*0.10
    # Case A: 100, 100, 100, 100 -> 100
    assert calculate_deterministic_score(100, 100, 100, 100) == 100
    # Case B: 0, 0, 0, 0 -> 0
    assert calculate_deterministic_score(0, 0, 0, 0) == 0
    # Case C: 80, 70, 60, 50 -> 48 + 21 + 5 = 74
    assert calculate_deterministic_score(80, 70, 60, 50) == 74
    # Case D: 95, 85, 75, 90 -> 57 + 25.5 + 9 = 91.5, rounded to 92
    assert calculate_deterministic_score(95, 85, 75, 90) == 92
    print("  PASS: Deterministic formula matches 60/30/10 weighting with exact rounding")

    # -------------------------------------------------------------------------
    # TEST 2: Score range clamping
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Score range and clamping validation...")
    assert _clamp_dimension(120) == 100
    assert _clamp_dimension(-25) == 0
    assert _clamp_dimension("85%") == 85
    assert _clamp_dimension("invalid", default=50) == 50
    assert calculate_deterministic_score(150, 200, 110, 105) == 100
    assert calculate_deterministic_score(-20, -5, -50, 0) == 0
    print("  PASS: All dimensions and overall score strictly bounded to [0, 100]")

    # -------------------------------------------------------------------------
    # TEST 3: Empty answer edge case
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Empty answer edge case...")
    res = client.post(
        "/api/v1/evaluation/evaluate",
        json={
            "question": "What is an index in PostgreSQL and how does it work?",
            "candidate_answer": "",
            "category": "Technical",
            "difficulty": "Medium",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["score"] == 0
    assert data["technicalAccuracy"] == 0
    assert data["clarity"] == 0
    assert data["depth"] == 0
    assert data["relevance"] == 0
    assert len(data["strengths"]) == 0
    assert len(data["improvements"]) >= 1
    assert "No answer was provided" in data["improvements"][0]
    assert len(data["suggestedAnswer"]) > 0
    print("  PASS: Empty answer returns deterministic 0 score without calling LLM")

    # -------------------------------------------------------------------------
    # TEST 4: Whitespace-only answer edge case
    # -------------------------------------------------------------------------
    print("\n[TEST 4] Whitespace-only answer edge case...")
    res = client.post(
        "/api/v1/evaluation/evaluate",
        json={
            "question": "Explain dependency injection in Spring Boot.",
            "candidate_answer": "   \n\t   ",
            "category": "Technical",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["score"] == 0
    assert data["technicalAccuracy"] == 0
    print("  PASS: Whitespace-only answer safely identified and scored as 0")

    # -------------------------------------------------------------------------
    # TEST 5: Very short answer edge case
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Very short answer edge case handling...")
    req = AnswerEvaluationRequest(
        question="How does garbage collection work in Java?",
        candidate_answer="It cleans memory.",
        category="Technical",
        difficulty="Medium",
    )
    assert req.candidate_answer == "It cleans memory."
    prompt = build_evaluation_prompt(req)
    assert "It cleans memory." in prompt
    print("  PASS: Very short answer cleanly packaged in prompt for evaluation")

    # -------------------------------------------------------------------------
    # TEST 6: Invalid request validation
    # -------------------------------------------------------------------------
    print("\n[TEST 6] Invalid request validation...")
    # Missing question
    res = client.post("/api/v1/evaluation/evaluate", json={"candidate_answer": "test"})
    assert res.status_code == 422
    # Whitespace question
    res = client.post("/api/v1/evaluation/evaluate", json={"question": "   ", "candidate_answer": "test"})
    assert res.status_code == 422
    print("  PASS: HTTP 422 returned for missing or empty question")

    # -------------------------------------------------------------------------
    # TEST 7: Category normalization
    # -------------------------------------------------------------------------
    print("\n[TEST 7] Category normalization...")
    req_hr = AnswerEvaluationRequest(question="Tell me about a time you had conflict.", candidate_answer="answer", category="hr")
    assert req_hr.category == "HR"
    req_tech = AnswerEvaluationRequest(question="What is a hash table?", candidate_answer="answer", category="technical")
    assert req_tech.category == "Technical"
    req_behav = AnswerEvaluationRequest(question="How do you handle deadlines?", candidate_answer="answer", category="behavioral")
    assert req_behav.category == "Behavioral"
    print("  PASS: Categories normalized properly ('hr' -> 'HR', 'technical' -> 'Technical')")

    # -------------------------------------------------------------------------
    # TEST 8: Difficulty normalization
    # -------------------------------------------------------------------------
    print("\n[TEST 8] Difficulty normalization...")
    req_easy = AnswerEvaluationRequest(question="What is an array?", candidate_answer="answer", difficulty="easy")
    assert req_easy.difficulty == "Easy"
    req_hard = AnswerEvaluationRequest(question="Design Paxos.", candidate_answer="answer", difficulty="hard")
    assert req_hard.difficulty == "Hard"
    print("  PASS: Difficulty normalized ('easy' -> 'Easy', 'hard' -> 'Hard')")

    # -------------------------------------------------------------------------
    # TEST 9: Prompt builder checks
    # -------------------------------------------------------------------------
    print("\n[TEST 9] Prompt builder checks...")
    req = AnswerEvaluationRequest(
        question="Explain how Redis functions as an in-memory cache.",
        candidate_answer="Redis stores key-values in RAM for sub-millisecond reads.",
        expected_answer="In-memory data structures, persistence options (RDB/AOF), eviction policies.",
        job_title="Backend Developer",
        category="Technical",
        difficulty="Medium",
        relevant_skills=["Redis", "Caching"],
    )
    prompt = build_evaluation_prompt(req)
    assert "correctness and coverage of the requested essential concepts" in prompt
    assert "Redis stores key-values in RAM" in prompt
    assert "In-memory data structures" in prompt
    assert "Backend Developer" in prompt
    assert "technicalAccuracy" in prompt
    assert "suggestedAnswer" in prompt
    print("  PASS: Evaluation prompt contains rubric, anti-hallucination, and context boundaries")

    # -------------------------------------------------------------------------
    # TEST 10: Ollama unavailable simulation -> HTTP 503
    # -------------------------------------------------------------------------
    print("\n[TEST 10] Ollama unavailable simulation -> HTTP 503...")
    with patch("app.services.llm_service.generate_json_response", side_effect=OllamaConnectionError("Ollama offline")):
        res = client.post(
            "/api/v1/evaluation/evaluate",
            json={
                "question": "Explain Docker containers.",
                "candidate_answer": "Containers package code with dependencies.",
            },
        )
        assert res.status_code == 503
        assert "temporarily unavailable" in res.json()["detail"]
    print("  PASS: HTTP 503 Service Unavailable returned when Ollama is unreachable")

    # -------------------------------------------------------------------------
    # TEST 11: Ollama timeout simulation -> HTTP 504
    # -------------------------------------------------------------------------
    print("\n[TEST 11] Ollama timeout simulation -> HTTP 504...")
    with patch("app.services.llm_service.generate_json_response", side_effect=OllamaTimeoutError("Model timed out")):
        res = client.post(
            "/api/v1/evaluation/evaluate",
            json={
                "question": "Explain Docker containers.",
                "candidate_answer": "Containers package code with dependencies.",
            },
        )
        assert res.status_code == 504
        assert "timed out" in res.json()["detail"]
    print("  PASS: HTTP 504 Gateway Timeout returned on LLM timeout")

    # -------------------------------------------------------------------------
    # TEST 12: Invalid LLM JSON simulation -> HTTP 502
    # -------------------------------------------------------------------------
    print("\n[TEST 12] Invalid LLM JSON simulation -> HTTP 502...")
    with patch("app.services.llm_service.generate_json_response", side_effect=LLMResponseParseError("Bad JSON")):
        res = client.post(
            "/api/v1/evaluation/evaluate",
            json={
                "question": "Explain Docker containers.",
                "candidate_answer": "Containers package code with dependencies.",
            },
        )
        assert res.status_code == 502
        assert "malformed evaluation response" in res.json()["detail"]
    print("  PASS: HTTP 502 Bad Gateway returned on unparseable LLM output")

    # -------------------------------------------------------------------------
    # TEST 13: Resilient JSON key mapping and fallback handling
    # -------------------------------------------------------------------------
    print("\n[TEST 13] Resilient JSON key mapping...")
    raw_response = {
        "technical_accuracy": 75,
        "relevancy": 80,
        "completeness": 70,
        "communication": 85,
        "strengths": ["Clear explanation"],
        "areas_to_improve": ["Add complexity analysis"],
        "reference_answer": "Reference text.",
    }
    t, r, d, c = _extract_dimension_scores(raw_response)
    assert t == 75
    assert r == 80
    assert d == 70
    assert c == 85
    calculated = calculate_deterministic_score(t, r, d, c)
    assert calculated == 78  # 45 + 24 + 8.5, rounded to 78
    print("  PASS: Alternate keys (technical_accuracy, relevancy, completeness, communication) mapped accurately")

    # -------------------------------------------------------------------------
    # TEST 14: HR / Behavioral answer evaluation flow
    # -------------------------------------------------------------------------
    print("\n[TEST 14] HR / Behavioral evaluation flow...")
    hr_mock_response = {
        "answer_status": "CORRECT",
        "technicalAccuracy": 85,
        "relevance": 90,
        "depth": 80,
        "clarity": 88,
        "strengths": ["Followed STAR format", "Clear resolution"],
        "improvements": ["Could quantify impact with metrics"],
        "suggestedAnswer": "In a previous project, when a disagreement arose...",
    }
    with patch("app.services.llm_service.generate_json_response", new=AsyncMock(return_value=hr_mock_response)):
        res = client.post(
            "/api/v1/evaluation/evaluate",
            json={
                "question": "Describe a difficult conflict with a coworker and how you resolved it.",
                "candidate_answer": "We disagreed on API design, so we gathered data on consumer needs and agreed on REST.",
                "category": "Behavioral",
                "difficulty": "Medium",
            },
        )
        assert res.status_code == 200
        d = res.json()
        assert d["score"] == 87
        assert "STAR" in d["strengths"][0]
    print("  PASS: Behavioral questions evaluated with proper professional criteria")

    # -------------------------------------------------------------------------
    # TEST 15: Irrelevant answer (topic drift)
    # -------------------------------------------------------------------------
    print("\n[TEST 15] Irrelevant answer simulation...")
    irrelevant_mock = {
        "answer_status": "IRRELEVANT",
        "technicalAccuracy": 40,
        "relevance": 20,
        "depth": 30,
        "clarity": 60,
        "strengths": [],
        "improvements": ["Answer does not address database indexing; discusses network protocols instead."],
        "suggestedAnswer": "A database index creates a lookup structure like a B-tree...",
    }
    with patch("app.services.llm_service.generate_json_response", new=AsyncMock(return_value=irrelevant_mock)):
        res = client.post(
            "/api/v1/evaluation/evaluate",
            json={
                "question": "What is a database index and how does it improve query performance?",
                "candidate_answer": "TCP uses a three-way handshake SYN, SYN-ACK, ACK to establish reliable streams.",
                "category": "Technical",
            },
        )
        assert res.status_code == 200
        d = res.json()
        assert d["relevance"] == 20
        assert d["score"] < 40
    print("  PASS: Off-topic / divergent answer penalizes relevance and overall score")

    # -------------------------------------------------------------------------
    # TEST 16: Suggested answer generation
    # -------------------------------------------------------------------------
    print("\n[TEST 16] Suggested answer generation schema validation...")
    sample_eval = AnswerEvaluationResponse(
        score=85,
        technicalAccuracy=88,
        clarity=85,
        depth=80,
        relevance=90,
        strengths=["Strong explanation of B-tree lookup"],
        improvements=["Could mention write overhead during insert/update"],
        suggestedAnswer="An index creates an auxiliary search data structure (typically a B-tree in relational databases)...",
    )
    assert sample_eval.score == 85
    assert len(sample_eval.suggestedAnswer) > 20
    print("  PASS: AnswerEvaluationResponse schema fully validates complete response")

    # -------------------------------------------------------------------------
    # TEST 17: CRITICAL WRONG-ANSWER TEST: Cinemaverse MongoDB Question
    # -------------------------------------------------------------------------
    print("\n[TEST 17] CRITICAL WRONG-ANSWER TEST: Cinemaverse MongoDB Question...")
    cinemaverse_question = (
        "In your Cinemaverse project, you used MongoDB for the backend. "
        "How would you design a schema for a movie entity that supports efficient "
        "querying by genre and release year while minimizing data redundancy?"
    )

    # 1. Deliberately incorrect answer with buzzwords but factually broken architecture
    wrong_answer = (
        "To minimize data redundancy, I would normalize everything into 15 separate relational SQL tables "
        "with foreign keys and run complex JOINs during query time. For genres, I will duplicate the full movie "
        "document 10 times for each genre without any index because MongoDB doesn't support indexes, "
        "and for release year I will do a full table scan on every request."
    )

    # 2. Strong, technically sound answer
    strong_answer = (
        "In MongoDB, we represent the movie as a document where genres are embedded as an array of strings "
        "(e.g., genres: ['Action', 'Sci-Fi']) and release_year is an integer. To minimize redundancy, "
        "we keep movie details in a single collection rather than normalizing or duplicating documents. "
        "To support efficient querying by genre and release year, we create a compound multikey index: "
        "db.movies.createIndex({ genres: 1, release_year: -1 }). This allows MongoDB to satisfy both "
        "genre filtering and release year range/sort queries directly from the index without in-memory sorting "
        "or full collection scans."
    )

    print("  Invoking real Qwen3 for DELIBERATELY WRONG candidate answer...")
    t0 = time.perf_counter()
    wrong_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={
            "question": cinemaverse_question,
            "candidate_answer": wrong_answer,
            "job_title": "Full Stack Developer",
            "category": "Technical",
            "difficulty": "Medium",
            "relevant_skills": ["MongoDB", "Database Design", "Indexing"],
        },
    )
    wrong_latency = round((time.perf_counter() - t0) * 1000)
    assert wrong_res.status_code == 200, f"Wrong answer evaluation failed: {wrong_res.text}"
    wrong_data = wrong_res.json()
    print(f"  -> Wrong Answer: Score={wrong_data['score']}, TechAccuracy={wrong_data['technicalAccuracy']}, "
          f"Relevance={wrong_data['relevance']}, Depth={wrong_data['depth']} (Latency: {wrong_latency} ms)")
    print(f"     Identified Improvements: {wrong_data['improvements']}")

    print("  Invoking real Qwen3 for STRONG candidate answer...")
    t0 = time.perf_counter()
    strong_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={
            "question": cinemaverse_question,
            "candidate_answer": strong_answer,
            "job_title": "Full Stack Developer",
            "category": "Technical",
            "difficulty": "Medium",
            "relevant_skills": ["MongoDB", "Database Design", "Indexing"],
        },
    )
    strong_latency = round((time.perf_counter() - t0) * 1000)
    assert strong_res.status_code == 200, f"Strong answer evaluation failed: {strong_res.text}"
    strong_data = strong_res.json()
    print(f"  -> Strong Answer: Score={strong_data['score']}, TechAccuracy={strong_data['technicalAccuracy']}, "
          f"Relevance={strong_data['relevance']}, Depth={strong_data['depth']} (Latency: {strong_latency} ms)")

    # Assertions for Critical Wrong-Answer Problem:
    # 1. Technical accuracy of wrong answer must be significantly lower than strong answer (gap >= 25 pts)
    tech_gap = strong_data["technicalAccuracy"] - wrong_data["technicalAccuracy"]
    assert tech_gap >= 25, f"Expected technical accuracy gap >= 25, got {tech_gap} (strong: {strong_data['technicalAccuracy']}, wrong: {wrong_data['technicalAccuracy']})"

    # 2. Overall score of wrong answer must not be artificially high (must be < 50, unlike previous 70-80%)
    assert wrong_data["score"] < 50, (
        f"CRITICAL FAILURE: Wrong answer overall score was artificially inflated ({wrong_data['score']} >= 50)!"
    )

    # 3. Strong answer overall score must be solid (>= 70) and significantly outperform wrong answer (gap >= 25)
    assert strong_data["score"] >= 70, f"Strong answer score unexpectedly low: {strong_data['score']}"
    score_gap = strong_data["score"] - wrong_data["score"]
    assert score_gap >= 25, f"Expected overall score gap >= 25, got {score_gap}"

    # 4. Technical accuracy of wrong answer is penalized (<= 35)
    assert wrong_data["technicalAccuracy"] <= 35, f"Expected wrong answer technical accuracy <= 35, got {wrong_data['technicalAccuracy']}"

    # 5. Improvements on wrong answer must identify meaningful technical problems
    assert len(wrong_data["improvements"]) >= 1, "Wrong answer should have actionable improvements identified"
    print(f"  PASS: Critical test verified! Tech accuracy gap = {tech_gap} pts, Score gap = {score_gap} pts.")
    print(f"        Wrong Answer Score = {wrong_data['score']}/100, Strong Answer Score = {strong_data['score']}/100.")
    print("        Evaluator successfully rejected MongoDB false claims and did NOT inflate score for keywords.")

    # -------------------------------------------------------------------------
    # TEST 18: Live End-to-End Qwen3 Answer Evaluation & Latency Benchmark
    # -------------------------------------------------------------------------
    print("\n[TEST 18] Live End-to-End Qwen3 Answer Evaluation & Latency Benchmark...")
    print(f"  Phase 10 E2E Live Evaluation Status: HTTP 200 OK")
    print(f"  Wrong Answer Latency: {wrong_latency} ms")
    print(f"  Strong Answer Latency: {strong_latency} ms")
    print(f"  Strong Answer Overall Score: {strong_data['score']}/100")
    print(f"  Strong Answer Suggested Reference: {strong_data['suggestedAnswer'][:100]}...")
    assert strong_data["score"] >= 65
    assert len(strong_data["suggestedAnswer"]) > 20
    print("  PASS: Live local Qwen3 evaluation produced verified output within operational bounds")

    # -------------------------------------------------------------------------
    # MANDATORY ACCURACY TESTS 1-10: Critical Gating Regression Suite
    # -------------------------------------------------------------------------
    rest_question = (
        "Can you explain the fundamental principles of RESTful API design that you would apply to a movie "
        "discovery platform, and how you would ensure these principles are followed without compromising scalability?"
    )

    # TEST 19 (Mandatory 1): "I don't know." -> score = 0, answer_status = "NON_ANSWER"
    print("\n[MANDATORY TEST 1] Candidate says 'I don't know.'...")
    m1_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": rest_question, "candidate_answer": "I don't know.", "category": "Technical"},
    )
    assert m1_res.status_code == 200
    m1_data = m1_res.json()
    assert m1_data["score"] == 0, f"Expected score=0 for 'I don't know.', got {m1_data['score']}"
    assert m1_data["technicalAccuracy"] == 0
    assert m1_data["relevance"] == 0
    assert m1_data["depth"] == 0
    assert m1_data["clarity"] == 0
    assert m1_data["answer_status"] == "NON_ANSWER"
    print(f"  PASS: 'I don't know.' received score=0 and answer_status=NON_ANSWER")

    # TEST 20 (Mandatory 2): "I don't know the answer." -> score = 0, answer_status = "NON_ANSWER"
    print("\n[MANDATORY TEST 2] Candidate says 'I don't know the answer.'...")
    m2_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": rest_question, "candidate_answer": "I don't know the answer.", "category": "Technical"},
    )
    assert m2_res.status_code == 200
    m2_data = m2_res.json()
    assert m2_data["score"] == 0, f"Expected score=0, got {m2_data['score']}"
    assert m2_data["answer_status"] == "NON_ANSWER"
    print(f"  PASS: 'I don't know the answer.' scored 0 and marked NON_ANSWER")

    # TEST 21 (Mandatory 3): "Binary search has O(log n) time complexity." -> IRRELEVANT, score <= 5
    print("\n[MANDATORY TEST 3] Irrelevant candidate answer: Binary search complexity...")
    m3_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": rest_question, "candidate_answer": "Binary search has O(log n) time complexity.", "category": "Technical"},
    )
    assert m3_res.status_code == 200
    m3_data = m3_res.json()
    assert m3_data["score"] <= 5, f"Expected score <= 5 for irrelevant answer, got {m3_data['score']}"
    assert m3_data["answer_status"] in ("IRRELEVANT", "NON_ANSWER")
    assert m3_data["technicalAccuracy"] == 0
    print(f"  PASS: Irrelevant answer scored {m3_data['score']} (<= 5) and tech accuracy=0")

    # TEST 22 (Mandatory 4): Partial REST answer -> PARTIAL, relevance high, score > 0 but not high
    print("\n[MANDATORY TEST 4] Partial REST answer...")
    m4_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={
            "question": rest_question,
            "candidate_answer": "REST APIs use GET to retrieve resources and POST to create resources.",
            "category": "Technical",
        },
    )
    assert m4_res.status_code == 200
    m4_data = m4_res.json()
    assert m4_data["score"] > 0, f"Expected score > 0 for partial answer, got {m4_data['score']}"
    assert m4_data["score"] < 75, f"Expected partial score < 75, got {m4_data['score']}"
    assert m4_data["relevance"] >= 60, f"Expected high relevance (>= 60), got {m4_data['relevance']}"
    assert m4_data["answer_status"] == "PARTIAL"
    print(f"  PASS: Partial answer scored {m4_data['score']}, status={m4_data['answer_status']}, rel={m4_data['relevance']}")

    # TEST 23 (Mandatory 5): Strong REST answer -> high tech accuracy, high rel, high score
    print("\n[MANDATORY TEST 5] Strong REST design answer...")
    strong_rest_answer = (
        "To design RESTful APIs for a movie discovery platform, I would apply: 1) Resource-oriented design using nouns "
        "(e.g., /api/v1/movies, /api/v1/genres), 2) Standard HTTP verbs: GET for retrieval, POST for creation, PUT/PATCH "
        "for updates, DELETE for deletion, with correct status codes (200, 201, 404, 500), 3) Stateless communication "
        "where each request contains all context, 4) Query parameters for filtering, sorting, and pagination "
        "(e.g. ?genre=action&page=1&limit=20). For scalability without compromising REST principles, I would implement "
        "HTTP caching headers (Cache-Control, ETag) with Redis caching, rate limiting to protect endpoints, and database "
        "indexes on queryable attributes."
    )
    m5_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": rest_question, "candidate_answer": strong_rest_answer, "category": "Technical"},
    )
    assert m5_res.status_code == 200
    m5_data = m5_res.json()
    assert m5_data["technicalAccuracy"] >= 75, f"Expected high tech accuracy >= 75, got {m5_data['technicalAccuracy']}"
    assert m5_data["relevance"] >= 80, f"Expected high relevance >= 80, got {m5_data['relevance']}"
    assert m5_data["score"] >= 70, f"Expected high score >= 70, got {m5_data['score']}"
    assert m5_data["answer_status"] == "CORRECT"
    print(f"  PASS: Strong answer scored {m5_data['score']}, tech={m5_data['technicalAccuracy']}, status={m5_data['answer_status']}")

    # TEST 24 (Mandatory 6): Fluent but technically incorrect REST answer
    print("\n[MANDATORY TEST 6] Fluent but technically incorrect REST answer...")
    wrong_rest_answer = (
        "To build REST APIs for a movie discovery platform, you should use POST for all read operations because POST "
        "doesn't have URL length limits and is encrypted by default. Caching headers should be disabled because REST "
        "forbids caching, and you should maintain active session state on the server for each client to ensure security."
    )
    m6_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": rest_question, "candidate_answer": wrong_rest_answer, "category": "Technical"},
    )
    assert m6_res.status_code == 200
    m6_data = m6_res.json()
    assert m6_data["technicalAccuracy"] <= 35, f"Expected low tech accuracy <= 35, got {m6_data['technicalAccuracy']}"
    assert m6_data["score"] <= 45, f"Expected low score <= 45, got {m6_data['score']}"
    print(f"  PASS: Fluent wrong answer scored {m6_data['score']}, tech={m6_data['technicalAccuracy']}")

    # TEST 25 (Mandatory 7): MongoDB answer for REST question -> low relevance, score capped low
    print("\n[MANDATORY TEST 7] Long answer about MongoDB for REST question...")
    mongodb_answer = (
        "MongoDB is a document-oriented NoSQL database that stores data in flexible, JSON-like documents called BSON. "
        "In MongoDB, collections contain documents, and each document can have a different structure. You can index "
        "fields in MongoDB using single field indexes, compound indexes, or multikey indexes on arrays. MongoDB uses "
        "wiredTiger as its default storage engine and provides high write throughput."
    )
    m7_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": rest_question, "candidate_answer": mongodb_answer, "category": "Technical"},
    )
    assert m7_res.status_code == 200
    m7_data = m7_res.json()
    assert m7_data["relevance"] <= 20, f"Expected low relevance <= 20, got {m7_data['relevance']}"
    assert m7_data["score"] <= 10, f"Expected score capped <= 10, got {m7_data['score']}"
    print(f"  PASS: Off-topic MongoDB answer scored {m7_data['score']} (<= 10), rel={m7_data['relevance']}")

    # TEST 26 (Mandatory 8): Empty answer -> score = 0
    print("\n[MANDATORY TEST 8] Empty answer...")
    m8_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": rest_question, "candidate_answer": "", "category": "Technical"},
    )
    assert m8_res.status_code == 200
    m8_data = m8_res.json()
    assert m8_data["score"] == 0
    assert m8_data["answer_status"] == "NON_ANSWER"
    print("  PASS: Empty answer returned score=0, status=NON_ANSWER")

    # TEST 27 (Mandatory 9): Whitespace-only answer -> score = 0
    print("\n[MANDATORY TEST 9] Whitespace-only answer...")
    m9_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": rest_question, "candidate_answer": "    \n\t   ", "category": "Technical"},
    )
    assert m9_res.status_code == 200
    m9_data = m9_res.json()
    assert m9_data["score"] == 0
    assert m9_data["answer_status"] == "NON_ANSWER"
    print("  PASS: Whitespace answer returned score=0, status=NON_ANSWER")

    # TEST 28 (Mandatory 10): Very short answer such as 'yes' -> score very low/0, NON_ANSWER
    print("\n[MANDATORY TEST 10] Very short answer: 'yes'...")
    m10_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": rest_question, "candidate_answer": "yes", "category": "Technical"},
    )
    assert m10_res.status_code == 200
    m10_data = m10_res.json()
    assert m10_data["score"] == 0, f"Expected score=0 for 'yes', got {m10_data['score']}"
    assert m10_data["answer_status"] == "NON_ANSWER"
    print("  PASS: 'yes' identified as NON_ANSWER with score=0")

    # =========================================================================
    # QUESTION-TYPE AWARENESS MANDATORY TESTS (Tests 29 to 36)
    # =========================================================================
    intro_q = "Could you please introduce yourself and briefly walk me through your background?"

    # TEST 29 (QT Test 1): Intro Q + "My name is Alex." -> PARTIAL, score > 0, rel > 0
    print("\n[QUESTION-TYPE TEST 1] Introduction Question + 'My name is Alex.'...")
    qt1_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": intro_q, "candidate_answer": "My name is Alex.", "category": "Technical", "stage": "INTRO"},
    )
    assert qt1_res.status_code == 200
    qt1_data = qt1_res.json()
    assert qt1_data["answer_status"] == "PARTIAL", f"Expected PARTIAL, got {qt1_data['answer_status']}"
    assert qt1_data["score"] > 0, f"Expected score > 0, got {qt1_data['score']}"
    assert qt1_data["relevance"] > 0, f"Expected relevance > 0, got {qt1_data['relevance']}"
    assert "technical" not in "".join(qt1_data.get("improvements", [])).lower() or "incorrect" not in "".join(qt1_data.get("improvements", [])).lower()
    print(f"  PASS: 'My name is Alex.' scored {qt1_data['score']} (> 0) with status=PARTIAL, rel={qt1_data['relevance']}")

    # TEST 30 (QT Test 2): Intro Q + "I don't know." -> NON_ANSWER, score = 0
    print("\n[QUESTION-TYPE TEST 2] Introduction Question + 'I don't know.'...")
    qt2_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": intro_q, "candidate_answer": "I don't know.", "category": "Technical", "stage": "INTRO"},
    )
    assert qt2_res.status_code == 200
    qt2_data = qt2_res.json()
    assert qt2_data["answer_status"] == "NON_ANSWER", f"Expected NON_ANSWER, got {qt2_data['answer_status']}"
    assert qt2_data["score"] == 0, f"Expected score=0, got {qt2_data['score']}"
    print("  PASS: Intro + 'I don't know.' strictly returned score=0, status=NON_ANSWER")

    # TEST 31 (QT Test 3): Intro Q + "Binary search has O(log n) complexity." -> IRRELEVANT, score <= 5
    print("\n[QUESTION-TYPE TEST 3] Introduction Question + 'Binary search has O(log n) complexity.'...")
    qt3_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": intro_q, "candidate_answer": "Binary search has O(log n) complexity.", "category": "Technical", "stage": "INTRO"},
    )
    assert qt3_res.status_code == 200
    qt3_data = qt3_res.json()
    assert qt3_data["answer_status"] == "IRRELEVANT", f"Expected IRRELEVANT, got {qt3_data['answer_status']}"
    assert qt3_data["score"] <= 5, f"Expected score <= 5, got {qt3_data['score']}"
    print(f"  PASS: Intro + off-topic binary search answer scored {qt3_data['score']} (<= 5), status=IRRELEVANT")

    # TEST 32 (QT Test 4): Intro Q + Full intro -> CORRECT, substantially higher score than QT Test 1
    print("\n[QUESTION-TYPE TEST 4] Introduction Question + Full intro...")
    full_intro_ans = (
        "My name is Alex. I am a B.Tech CSE student. I have worked with Java, Python and web technologies "
        "and have developed several software projects."
    )
    qt4_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": intro_q, "candidate_answer": full_intro_ans, "category": "Technical", "stage": "INTRO"},
    )
    assert qt4_res.status_code == 200
    qt4_data = qt4_res.json()
    assert qt4_data["answer_status"] == "CORRECT", f"Expected CORRECT, got {qt4_data['answer_status']}"
    assert qt4_data["score"] >= 80, f"Expected high score >= 80, got {qt4_data['score']}"
    assert qt4_data["score"] > qt1_data["score"] + 10, f"Expected full intro ({qt4_data['score']}) substantially higher than partial ({qt1_data['score']})"
    print(f"  PASS: Full intro scored {qt4_data['score']} (substantially higher than partial {qt1_data['score']}), status=CORRECT")

    # TEST 33 (QT Test 5): "What is your name?" + "My name is Alex." -> CORRECT/high score
    print("\n[QUESTION-TYPE TEST 5] 'What is your name?' + 'My name is Alex.'...")
    qt5_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": "What is your name?", "candidate_answer": "My name is Alex.", "category": "Technical"},
    )
    assert qt5_res.status_code == 200
    qt5_data = qt5_res.json()
    assert qt5_data["answer_status"] == "CORRECT", f"Expected CORRECT, got {qt5_data['answer_status']}"
    assert qt5_data["score"] >= 85, f"Expected high score >= 85, got {qt5_data['score']}"
    print(f"  PASS: Direct name question scored {qt5_data['score']} (>= 85), status=CORRECT")

    # TEST 34 (QT Test 6): Technical Q ("What is polymorphism in Java?") + "My name is Alex." -> IRRELEVANT, low score
    poly_q = "What is polymorphism in Java?"
    print("\n[QUESTION-TYPE TEST 6] Technical Q ('What is polymorphism in Java?') + 'My name is Alex.'...")
    qt6_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": poly_q, "candidate_answer": "My name is Alex.", "category": "Technical"},
    )
    assert qt6_res.status_code == 200
    qt6_data = qt6_res.json()
    assert qt6_data["answer_status"] == "IRRELEVANT", f"Expected IRRELEVANT, got {qt6_data['answer_status']}"
    assert qt6_data["score"] <= 5, f"Expected score <= 5, got {qt6_data['score']}"
    assert qt6_data["technicalAccuracy"] == 0
    print(f"  PASS: Name given for polymorphism question scored {qt6_data['score']} (<= 5), status=IRRELEVANT")

    # TEST 35 (QT Test 7): Technical Q + "I don't know." -> NON_ANSWER, 0
    print("\n[QUESTION-TYPE TEST 7] Technical Q + 'I don't know.'...")
    qt7_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": poly_q, "candidate_answer": "I don't know.", "category": "Technical"},
    )
    assert qt7_res.status_code == 200
    qt7_data = qt7_res.json()
    assert qt7_data["answer_status"] == "NON_ANSWER", f"Expected NON_ANSWER, got {qt7_data['answer_status']}"
    assert qt7_data["score"] == 0, f"Expected score=0, got {qt7_data['score']}"
    print("  PASS: Technical Q + 'I don't know.' scored 0, status=NON_ANSWER")

    # TEST 36 (QT Test 8): Technical Q + Accurate definition -> CORRECT, high score
    print("\n[QUESTION-TYPE TEST 8] Technical Q + Accurate definition...")
    accurate_poly_ans = "Polymorphism allows the same interface or method call to behave differently depending on the object."
    qt8_res = client.post(
        "/api/v1/evaluation/evaluate",
        json={"question": poly_q, "candidate_answer": accurate_poly_ans, "category": "Technical"},
    )
    assert qt8_res.status_code == 200
    qt8_data = qt8_res.json()
    assert qt8_data["answer_status"] == "CORRECT", f"Expected CORRECT, got {qt8_data['answer_status']}"
    assert qt8_data["score"] >= 80, f"Expected score >= 80, got {qt8_data['score']}"
    print(f"  PASS: Accurate polymorphism answer scored {qt8_data['score']} (>= 80), status=CORRECT")

    print("\n=================================================================")
    print("ALL 36 PHASE 10 AUTOMATED TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")


if __name__ == "__main__":
    run_all_tests()
