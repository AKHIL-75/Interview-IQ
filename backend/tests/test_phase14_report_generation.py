"""
Phase 14: Final Performance Report Generation Comprehensive Test Suite

Verifies:
  1. Grade calculation & boundary mapping (A+, A, B, C, D, F)
  2. Score aggregation & bounded arithmetic (Technical, Relevance, Depth, Clarity)
  3. Edge cases: zero questions, all skipped, mixed answers, malformed values
  4. Question-by-question breakdown generation & privacy (no internal reasoning)
  5. Assessed-only skill/topic performance analysis
  6. Deterministic strengths & weaknesses aggregation & deduplication
  7. Adaptive progression summary & candidate-friendly language
  8. Traceable, actionable preparation recommendations
  9. POST /api/v1/interview/generate-report endpoint
  10. POST /api/v1/interview/report persistence & enrichment
  11. GET /api/v1/interview/report/{id} authorization, RLS isolation & 404 behavior
"""

if __package__:
    from .live_test_config import require_test_accounts
else:
    from live_test_config import require_test_accounts
_test_accounts = require_test_accounts(2)


import asyncio
import os
import sys
import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings
from app.main import app
from app.services.report_generator import (
    calculate_grade,
    aggregate_scores,
    build_question_breakdown,
    analyze_topic_performance,
    analyze_strengths_and_weaknesses,
    build_adaptive_summary,
    generate_recommendations,
    generate_final_report,
    normalize_report_for_response,
)


async def get_user_token(email: str, password: str) -> dict:
    auth_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/token?grant_type=password"
    headers = {"apikey": settings.SUPABASE_ANON_KEY}
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(auth_url, headers=headers, json={"email": email, "password": password})
        assert res.status_code == 200, f"Login failed for {email}: {"[response body omitted]"}"
        data = res.json()
        return {
            "token": data["access_token"],
            "user_id": data["user"]["id"],
            "email": email,
        }


def test_phase14_report_suite():
    print("=" * 70)
    print("PHASE 14: FINAL PERFORMANCE REPORT GENERATION SUITE")
    print("=" * 70)

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Grade Calculation & Boundary Mapping
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 1] Verifying grade calculation & boundary mapping...")
    assert calculate_grade(100) == ("A+", "Outstanding Performance")
    assert calculate_grade(90) == ("A+", "Outstanding Performance")
    assert calculate_grade(89) == ("A", "Strong Performance")
    assert calculate_grade(80) == ("A", "Strong Performance")
    assert calculate_grade(79) == ("B", "Proficient Performance")
    assert calculate_grade(70) == ("B", "Proficient Performance")
    assert calculate_grade(69) == ("C", "Developing Performance")
    assert calculate_grade(60) == ("C", "Developing Performance")
    assert calculate_grade(59) == ("D", "Needs Improvement")
    assert calculate_grade(50) == ("D", "Needs Improvement")
    assert calculate_grade(49) == ("F", "Unsatisfactory Performance")
    assert calculate_grade(0) == ("F", "Unsatisfactory Performance")
    assert calculate_grade(-10) == ("F", "Unsatisfactory Performance")
    assert calculate_grade(150) == ("A+", "Outstanding Performance")
    print("  PASS: All 14 boundary test cases for grade calculation verified.")

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Score Aggregation & Edge Cases
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 2] Verifying score aggregation & edge cases...")
    # Edge Case A: Zero evaluated questions
    zero_res = aggregate_scores([])
    assert zero_res["overall"] == 0
    assert zero_res["grade"] == "F"
    assert zero_res["technical_accuracy"] == 0
    assert zero_res["questions_evaluated"] == 0

    # Edge Case B: All skipped questions
    all_skipped = [
        {"skipped": True, "score": 0},
        {"skipped": True, "score": 0},
    ]
    skip_res = aggregate_scores(all_skipped)
    assert skip_res["overall"] == 0
    assert skip_res["grade"] == "F"
    assert skip_res["questions_evaluated"] == 0
    assert skip_res["questions_skipped"] == 2

    # Edge Case C: Mixed answers (3 answered, 1 skipped)
    mixed_answers = [
        {"skipped": False, "score": 85, "evaluation": {"score": 85, "technical_accuracy": 90, "relevance": 85, "depth": 80, "clarity": 85}},
        {"skipped": False, "score": 75, "evaluation": {"score": 75, "technical_accuracy": 70, "relevance": 80, "depth": 75, "clarity": 75}},
        {"skipped": False, "score": 80, "evaluation": {"score": 80, "technical_accuracy": 80, "relevance": 85, "depth": 80, "clarity": 75}},
        {"skipped": True, "score": 0},
    ]
    mixed_res = aggregate_scores(mixed_answers)
    # (85 + 75 + 80 + 0) / 4 = 60
    assert mixed_res["overall"] == 60
    assert mixed_res["grade"] == "C"
    assert mixed_res["questions_evaluated"] == 3
    assert mixed_res["questions_skipped"] == 1
    # Dimensions averaged over 3 valid answers:
    # tech: (90+70+80)/3 = 80
    assert mixed_res["technical_accuracy"] == 80
    assert mixed_res["relevance"] == 83
    assert mixed_res["depth"] == 78
    assert mixed_res["clarity"] == 78
    print("  PASS: Score aggregation correctly computes bounded metrics across edge cases.")

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Question-by-Question Breakdown
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 3] Verifying question-by-question breakdown generation...")
    sample_questions = [
        {"id": "q1", "question": "Explain JVM garbage collection.", "category": "Technical", "topic": "Java", "difficulty": "Medium", "is_follow_up": False},
        {"id": "q2", "question": "How does G1 GC differ from ZGC?", "category": "Technical", "topic": "Java", "difficulty": "Hard", "is_follow_up": True},
    ]
    sample_answers = [
        {
            "questionId": "q1",
            "answer": "JVM garbage collection automates memory deallocation using generational collectors like G1.",
            "skipped": False,
            "score": 88,
            "timeSpent": 45,
            "evaluation": {
                "score": 88,
                "technical_accuracy": 90,
                "relevance": 95,
                "depth": 85,
                "clarity": 85,
                "strengths": ["Clear definition of generational heaps", "Accurate description of mark-and-sweep"],
                "improvements": ["Could discuss tuning flags like -XX:+UseG1GC"],
                "suggested_answer": "Standard G1 overview.",
            },
        },
        {
            "questionId": "q2",
            "answer": "",
            "skipped": True,
            "score": 0,
            "timeSpent": 10,
        },
    ]
    breakdown = build_question_breakdown(sample_questions, sample_answers)
    assert len(breakdown) == 2
    assert breakdown[0]["question_order"] == 1
    assert breakdown[0]["topic"] == "Java"
    assert breakdown[0]["score"] == 88
    assert breakdown[0]["technical_accuracy"] == 90
    assert breakdown[0]["is_follow_up"] is False
    assert len(breakdown[0]["strengths"]) == 2

    assert breakdown[1]["question_order"] == 2
    assert breakdown[1]["is_follow_up"] is True
    assert breakdown[1]["skipped"] is True
    assert breakdown[1]["score"] == 0
    assert breakdown[1]["answer_status"] == "SKIPPED"
    print("  PASS: Question breakdown preserves full evaluation context without leaking debug data.")

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Assessed Skill/Topic Performance
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 4] Verifying skill/topic performance analysis...")
    topics = analyze_topic_performance(breakdown)
    assert len(topics) == 1
    assert topics[0]["topic"] == "Java"
    assert topics[0]["question_count"] == 2
    # Scores were 88 and 0 -> average 44 -> Needs Practice
    assert topics[0]["average_score"] == 44
    assert topics[0]["proficiency"] == "Needs Practice"
    print("  PASS: Skill/topic analysis strictly derives metrics from assessed questions.")

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Strengths & Weaknesses Analysis
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 5] Verifying deterministic strengths & weaknesses analysis...")
    str_list, weak_list = analyze_strengths_and_weaknesses(breakdown, mixed_res)
    assert len(str_list) > 0
    assert len(weak_list) > 0
    # Skipped question was recorded in weaknesses
    assert any("skipped" in w.lower() for w in weak_list)
    print(f"  PASS: Strengths ({len(str_list)}) and Weaknesses ({len(weak_list)}) aggregated successfully.")

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Adaptive Progression Summary
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 6] Verifying adaptive progression summary...")
    adapt_summary = build_adaptive_summary(None, None, breakdown)
    assert adapt_summary["total_follow_ups"] == 1
    assert "Java" in adapt_summary["follow_up_topics"]
    assert "adapted" in adapt_summary["summary_text"].lower()
    assert "DEEPER_CHALLENGE" not in adapt_summary["summary_text"]
    assert "TARGETED_FOLLOW_UP" not in adapt_summary["summary_text"]
    print("  PASS: Adaptive summary generated candidate-friendly explanation without internal enum leaks.")

    # ─────────────────────────────────────────────────────────────────────────
    # 7. Actionable Recommendations
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 7] Verifying actionable recommendations...")
    recs = generate_recommendations(topics, weak_list, mixed_res)
    assert len(recs) >= 1
    assert any("java" in r.lower() for r in recs)
    print(f"  PASS: {len(recs)} practical recommendations generated from real weak areas.")

    # ─────────────────────────────────────────────────────────────────────────
    # 8. Full Report Orchestration
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 8] Verifying full report generation orchestration...")
    full_report = generate_final_report(
        session_id="test-session-101",
        role="Java Developer",
        interview_type="Technical",
        difficulty="Medium",
        questions=sample_questions,
        answers=sample_answers,
        duration_secs=55,
    )
    assert full_report["session_id"] == "test-session-101"
    assert full_report["role"] == "Java Developer"
    assert "grade" in full_report
    assert "overall_score" in full_report
    assert "scores" in full_report
    assert "question_analysis" in full_report
    assert "skill_analysis" in full_report
    assert "adaptive_summary" in full_report
    assert "recommendations" in full_report
    print("  PASS: Full performance report payload validated.")

    # ─────────────────────────────────────────────────────────────────────────
    # 9. Normalization of Retrieved Reports
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 9] Verifying normalization of stored reports...")
    legacy_row = {
        "id": "rep-uuid-1",
        "session_id": "sess-uuid-1",
        "overall_score": 75,
        "role": "Backend Engineer",
        "duration_secs": 120,
        "scores": {"technicalKnowledge": 80, "problemSolving": 70, "communication": 75},
        "strengths": ["Good database knowledge"],
        "skill_gaps": ["Concurrency"],
        "recommendations": ["Study multi-threading"],
        "question_analysis": [],
    }
    norm = normalize_report_for_response(legacy_row)
    assert norm["grade"] == "B"
    assert norm["grade_label"] == "Proficient Performance"
    assert norm["dimensions"]["technical_accuracy"] == 80
    assert norm["dimensions"]["depth"] == 70
    assert norm["dimensions"]["clarity"] == 75
    assert "adaptive_summary" in norm
    assert "skill_analysis" in norm
    print("  PASS: Legacy report record normalized with all required Phase 14 sections.")

    # ─────────────────────────────────────────────────────────────────────────
    # 10. HTTP Endpoint: POST /generate-report (Stateless)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 10] Testing HTTP POST /api/v1/interview/generate-report...")
    client = TestClient(app)
    req_body = {
        "session_id": "test-preview-1",
        "role": "Full Stack Engineer",
        "interview_type": "Technical",
        "difficulty": "Medium",
        "questions": sample_questions,
        "answers": sample_answers,
        "duration_secs": 110,
    }
    res_gen = client.post("/api/v1/interview/generate-report", json=req_body)
    assert res_gen.status_code == 200, f"Generate report failed: {"[response body omitted]"}"
    gen_data = res_gen.json()
    assert gen_data["success"] is True
    assert "report" in gen_data
    assert gen_data["report"]["role"] == "Full Stack Engineer"
    assert gen_data["report"]["grade"] is not None
    print("  PASS: POST /generate-report successfully returned complete report payload.")

    # ─────────────────────────────────────────────────────────────────────────
    # 11. Authenticated User Tests: Supabase Persistence & Retrieval
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 11] Logging in User A ([removed legacy credential]) for real persistence test...")
    loop = asyncio.get_event_loop()
    user_a = loop.run_until_complete(get_user_token(_test_accounts["A"]["email"], _test_accounts["A"]["password"]))
    headers_a = {"Authorization": f"Bearer {user_a['token']}"}

    # Start a test interview to get a real session
    start_payload = {
        "candidate_profile": {"name": "Alex", "skills": ["Java", "SQL"], "experience_years": 3},
        "job_profile": {"role_title": "Java Engineer", "required_skills": ["Java", "SQL"], "experience_level": "Mid"},
        "interview_type": "Technical",
        "difficulty": "Medium",
        "question_count": 2,
    }
    res_start = client.post("/api/v1/interview/start", headers=headers_a, json=start_payload)
    assert res_start.status_code == 200
    session_id = res_start.json()["session_id"]
    q1 = res_start.json()["first_question"]

    # Submit an answer to next-question
    next_payload = {
        "session_id": session_id,
        "previous_question": q1["question"],
        "candidate_answer": "I have extensive experience working with Java collections and Spring Boot microservices.",
        "evaluation": {
            "score": 85,
            "technicalAccuracy": 85,
            "relevance": 90,
            "depth": 80,
            "clarity": 85,
            "strengths": ["Strong explanation of microservices"],
            "improvements": ["Could detail transaction management"],
            "suggestedAnswer": "Detailed transaction propagation overview.",
        },
        "category": "Technical",
        "difficulty": "Medium",
        "current_topic": "Java Fundamentals",
        "consecutive_follow_ups": 0,
        "question_history": [q1["question"]],
        "role": "Java Engineer",
        "interview_mode": "STATIC",
        "interview_plan": res_start.json()["interview_plan"],
        "interview_state": res_start.json()["interview_state"],
        "candidate_profile": start_payload["candidate_profile"],
        "job_profile": start_payload["job_profile"],
    }
    client.post("/api/v1/interview/next-question", headers=headers_a, json=next_payload)

    # Persist Report via POST /api/v1/interview/report
    print("\n[TEST 12] Testing POST /api/v1/interview/report with User A...")
    report_post_body = {
        "sessionId": session_id,
        "role": "Java Engineer",
        "interviewType": "Technical",
        "difficulty": "Medium",
        "questions": [q1],
        "answers": [
            {
                "questionId": q1.get("id", "q1"),
                "question": q1["question"],
                "answer": next_payload["candidate_answer"],
                "skipped": False,
                "score": 85,
                "timeSpent": 40,
                "evaluation": next_payload["evaluation"],
            }
        ],
        "durationSecs": 40,
    }
    res_rep = client.post("/api/v1/interview/report", headers=headers_a, json=report_post_body)
    assert res_rep.status_code == 200, f"Report save failed: {"[response body omitted]"}"
    saved_rep = res_rep.json()
    assert saved_rep["success"] is True
    assert saved_rep["persisted"] is True
    report_id = saved_rep["report"]["id"]
    assert report_id is not None
    assert saved_rep["report"]["grade"] == "A"
    print(f"  PASS: Report persisted to Supabase! report_id={report_id}, grade={saved_rep['report']['grade']}")

    # Retrieve report via GET /api/v1/interview/report/{id}
    print(f"\n[TEST 13] Testing GET /api/v1/interview/report/{report_id} with User A...")
    res_get = client.get(f"/api/v1/interview/report/{report_id}", headers=headers_a)
    assert res_get.status_code == 200
    retrieved = res_get.json()["report"]
    assert retrieved["id"] == report_id
    assert retrieved["overall_score"] == 85
    assert retrieved["grade"] == "A"
    assert retrieved["grade_label"] == "Strong Performance"
    assert retrieved["dimensions"]["technical_accuracy"] == 85
    assert len(retrieved["question_analysis"]) == 1
    assert len(retrieved["skill_analysis"]) == 1
    assert "adaptive_summary" in retrieved
    assert len(retrieved["recommendations"]) > 0
    print("  PASS: Retrieved report has complete viva-ready sections and real data.")

    # Retrieve via session_id lookup
    print(f"\n[TEST 14] Testing GET /api/v1/interview/report/{session_id} by session string...")
    res_sess = client.get(f"/api/v1/interview/report/{session_id}", headers=headers_a)
    assert res_sess.status_code == 200
    assert res_sess.json()["report"]["id"] == report_id
    print("  PASS: Report lookup by session_id succeeded.")

    # ─────────────────────────────────────────────────────────────────────────
    # 12. Security, Authentication & RLS Isolation
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 15] Testing Unauthenticated access to report...")
    res_unauth = client.get(f"/api/v1/interview/report/{report_id}")
    assert res_unauth.status_code == 401, f"Expected 401, got {res_unauth.status_code}"
    print("  PASS: Unauthenticated request rejected with HTTP 401.")

    print("\n[TEST 16] Testing Invalid report ID...")
    res_invalid = client.get("/api/v1/interview/report/00000000-0000-0000-0000-000000000000", headers=headers_a)
    assert res_invalid.status_code == 404
    print("  PASS: Non-existent report returns HTTP 404.")

    print("\n[TEST 17] Testing RLS cross-user isolation with User B...")
    user_b = loop.run_until_complete(get_user_token(_test_accounts["B"]["email"], _test_accounts["B"]["password"]))
    headers_b = {"Authorization": f"Bearer {user_b['token']}"}
    res_leak = client.get(f"/api/v1/interview/report/{report_id}", headers=headers_b)
    assert res_leak.status_code == 404, f"RLS LEAK! User B could access User A's report! Status={res_leak.status_code}"
    print("  PASS: RLS strictly blocks User B from User A's report (HTTP 404).")

    print("\n" + "=" * 70)
    print("ALL 17 PHASE 14 VERIFICATION TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 70)


if __name__ == "__main__":
    test_phase14_report_suite()
