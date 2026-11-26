"""
Comprehensive test suite for Phase 8: Interview State Management & Live Session.

Covers:
- Test 1: Session initialization (status="active", stable ID, timestamps)
- Test 2: Session creation with Phase 7 generated questions
- Test 3: Stable session ID (consistent and verifiable format)
- Test 4: First question index = 0
- Test 5: Question count integrity (length matches generated question count)
- Test 6: Answer persistence with valid timestamps
- Test 7: Answer associated with correct question ID
- Test 8: Question transition index advancement (0 -> 1 -> 2 ...)
- Test 9: Skip persistence (marked skipped=True, empty answer, recorded in skipped_questions)
- Test 10: Duplicate answer prevention (submitting same question updates record without duplicating)
- Test 11: Duplicate skip prevention (skipping same question updates without duplicating)
- Test 12: Progress calculation (answered_count, skipped_count, remaining_count, progress_percent)
- Test 13: Invalid index protection (negative index or out-of-bounds clamped safely)
- Test 14: Corrupted storage recovery (malformed data handled safely without unhandled crashes)
- Test 15: Active session restoration from valid serialized dictionary
- Test 16: Refresh recovery simulation (state restored at mid-interview position with history intact)
- Test 17: Final-question completion transition (advance beyond last question safely refused)
- Test 18: Completed session state (status="completed", completed_at populated, data preserved)
- Test 19: No data loss after refresh (questions, answers, skips, timer reference intact)
- Test 20: Existing Phase 7 generated question structure remains intact
"""

import os
import sys
import time

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.schemas.interview import (
    GeneratedQuestion,
    InterviewAnswerRecord,
    InterviewProgressStats,
    InterviewSessionState,
)


def sample_phase7_questions() -> list[GeneratedQuestion]:
    """Sample generated questions conforming strictly to Phase 7 schema."""
    return [
        GeneratedQuestion(
            id="q1",
            question="How do you optimize high-throughput database queries in PostgreSQL?",
            category="Technical",
            topic="SQL",
            difficulty="Medium",
            focus="Matched Skill",
            expected_aspects=["Indexing strategies", "EXPLAIN ANALYZE interpretation"],
        ),
        GeneratedQuestion(
            id="q2",
            question="Describe your experience refactoring a Spring Boot microservice.",
            category="Technical",
            topic="Spring Boot",
            difficulty="Medium",
            focus="Matched Skill",
            expected_aspects=["Decoupling components", "Zero downtime deployment"],
        ),
        GeneratedQuestion(
            id="q3",
            question="How do you manage deadlines when technical requirements suddenly shift?",
            category="HR",
            topic="Adaptability",
            difficulty="Medium",
            focus="Behavioral",
            expected_aspects=["Stakeholder communication", "Priority triage"],
        ),
        GeneratedQuestion(
            id="q4",
            question="What is your approach to learning a new language like Python in 30 days?",
            category="Technical",
            topic="Python",
            difficulty="Medium",
            focus="Skill Gap",
            expected_aspects=["Structured learning roadmap", "Hands-on projects"],
        ),
    ]


def run_all_tests():
    print("=================================================================")
    print("STARTING PHASE 8 AUTOMATED TEST SUITE")
    print("=================================================================\n")

    questions = sample_phase7_questions()
    t0 = int(time.time() * 1000)

    # -------------------------------------------------------------
    # TEST 1: Session initialization
    # -------------------------------------------------------------
    print("[TEST 1] Session initialization...")
    session = InterviewSessionState(
        session_id=f"session-{t0}",
        created_at=t0,
        started_at=t0,
        status="active",
        questions=questions,
        current_question_index=0,
        answers=[],
        skipped_questions=[],
        current_question_started_at=t0,
        completed_at=None,
        interview_config={"role": "Java Backend Engineer", "difficulty": "Medium"},
    )
    assert session.status == "active"
    assert session.started_at == t0
    assert session.completed_at is None
    print("  PASS: Session successfully initialized with status='active'")

    # -------------------------------------------------------------
    # TEST 2: Session creation with Phase 7 generated questions
    # -------------------------------------------------------------
    print("\n[TEST 2] Session creation with Phase 7 generated questions...")
    assert len(session.questions) == 4
    assert session.questions[0].id == "q1"
    assert session.questions[1].id == "q2"
    print("  PASS: Session contains exactly 4 Phase 7 generated questions")

    # -------------------------------------------------------------
    # TEST 3: Stable session ID
    # -------------------------------------------------------------
    print("\n[TEST 3] Stable session ID verification...")
    stable_id = session.session_id
    assert stable_id.startswith("session-")
    assert len(stable_id) > 10
    # Simulate round-trip serialization
    dumped = session.model_dump()
    assert dumped["session_id"] == stable_id
    print(f"  PASS: Session ID '{stable_id}' remains stable across operations")

    # -------------------------------------------------------------
    # TEST 4: First question index = 0
    # -------------------------------------------------------------
    print("\n[TEST 4] First question index = 0...")
    assert session.current_question_index == 0
    current_q = session.get_current_question()
    assert current_q is not None
    assert current_q.id == "q1"
    print(f"  PASS: Initial question index is 0 pointing to '{current_q.id}'")

    # -------------------------------------------------------------
    # TEST 5: Question count integrity
    # -------------------------------------------------------------
    print("\n[TEST 5] Question count integrity...")
    assert len(session.questions) == len(questions) == 4
    print("  PASS: Question count matches original Phase 7 list (4 questions)")

    # -------------------------------------------------------------
    # TEST 6: Answer persistence with valid timestamps
    # -------------------------------------------------------------
    print("\n[TEST 6] Answer persistence with valid timestamps...")
    t_answer1 = t0 + 15000  # 15 seconds later
    rec1 = session.add_or_update_answer(
        question_id="q1",
        answer_text="I analyze execution plans using EXPLAIN ANALYZE and add B-Tree indexes on filtered columns.",
        submitted_at=t_answer1,
        started_at=t0,
        time_spent=15,
        evaluation={"score": 85, "technicalAccuracy": 88},
    )
    assert len(session.answers) == 1
    assert session.answers[0].answer.startswith("I analyze execution plans")
    assert session.answers[0].submitted_at == t_answer1
    assert session.answers[0].time_spent == 15
    assert session.answers[0].skipped is False
    print("  PASS: Answer 1 persisted with valid timestamps and time_spent=15s")

    # -------------------------------------------------------------
    # TEST 7: Answer associated with correct question
    # -------------------------------------------------------------
    print("\n[TEST 7] Answer associated with correct question ID...")
    assert session.answers[0].question_id == "q1"
    assert session.answers[0].question == session.questions[0].question
    print(f"  PASS: Answer is mapped directly to '{session.answers[0].question_id}'")

    # -------------------------------------------------------------
    # TEST 8: Question transition index advancement
    # -------------------------------------------------------------
    print("\n[TEST 8] Question transition (0 -> 1)...")
    t_next1 = t0 + 16000
    advanced = session.advance_question(timestamp=t_next1)
    assert advanced is True
    assert session.current_question_index == 1
    assert session.current_question_started_at == t_next1
    q_curr = session.get_current_question()
    assert q_curr.id == "q2"
    print(f"  PASS: Advanced safely to index 1 (Question '{q_curr.id}')")

    # -------------------------------------------------------------
    # TEST 9: Skip persistence
    # -------------------------------------------------------------
    print("\n[TEST 9] Skip persistence on Question 2...")
    t_skip2 = t_next1 + 8000
    rec2 = session.skip_question(
        question_id="q2",
        submitted_at=t_skip2,
        started_at=t_next1,
        time_spent=8,
    )
    assert rec2.skipped is True
    assert rec2.answer == ""
    assert "q2" in session.skipped_questions
    assert len(session.answers) == 2
    assert session.answers[1].question_id == "q2"
    assert session.answers[1].skipped is True
    print("  PASS: Question 2 marked as skipped in answers and skipped_questions")

    # -------------------------------------------------------------
    # TEST 10: Duplicate answer prevention
    # -------------------------------------------------------------
    print("\n[TEST 10] Duplicate answer prevention (re-submitting Question 1)...")
    # Simulate user or double-click submitting Question 1 again with modified answer
    t_resubmit = t_skip2 + 2000
    rec1_updated = session.add_or_update_answer(
        question_id="q1",
        answer_text="Updated answer: Using covering indexes and vacuuming.",
        submitted_at=t_resubmit,
        started_at=t0,
        time_spent=20,
    )
    # Total answers count must NOT increase
    assert len(session.answers) == 2, f"Expected 2 answers, got {len(session.answers)}"
    assert session.answers[0].question_id == "q1"
    assert session.answers[0].answer.startswith("Updated answer:")
    assert session.answers[0].time_spent == 20
    print("  PASS: Duplicate answer prevented; record updated in place")

    # -------------------------------------------------------------
    # TEST 11: Duplicate skip prevention
    # -------------------------------------------------------------
    print("\n[TEST 11] Duplicate skip prevention (skipping Question 2 again)...")
    rec2_skipped_again = session.skip_question(
        question_id="q2",
        submitted_at=t_resubmit + 1000,
        started_at=t_next1,
        time_spent=10,
    )
    assert len(session.answers) == 2
    assert session.skipped_questions.count("q2") == 1
    print("  PASS: Duplicate skip prevented; count remains 2 and skipped_questions deduplicated")

    # -------------------------------------------------------------
    # TEST 12: Progress calculation
    # -------------------------------------------------------------
    print("\n[TEST 12] Progress calculation...")
    progress = session.get_progress()
    assert progress.total_questions == 4
    assert progress.answered_count == 1  # q1 is answered, q2 is skipped
    assert progress.skipped_count == 1   # q2 is skipped
    assert progress.remaining_count == 2 # q3 and q4 remaining
    assert progress.progress_percent == 50  # 2 of 4 processed = 50%
    print(f"  PASS: Progress computed correctly: {progress.progress_percent}% ({progress.answered_count} answered, {progress.skipped_count} skipped, {progress.remaining_count} remaining)")

    # -------------------------------------------------------------
    # TEST 13: Invalid index protection
    # -------------------------------------------------------------
    print("\n[TEST 13] Invalid index protection...")
    # Test negative index clamping via validator
    state_neg = InterviewSessionState(
        session_id="test-neg",
        created_at=t0,
        started_at=t0,
        status="active",
        questions=questions,
        current_question_index=-5,
        current_question_started_at=t0,
    )
    assert state_neg.current_question_index == 0

    # Test out of bounds index via restore_safely
    data_oob = state_neg.model_dump()
    data_oob["current_question_index"] = 999
    restored_oob = InterviewSessionState.restore_safely(data_oob)
    assert restored_oob is not None
    assert restored_oob.current_question_index == len(questions) - 1
    print("  PASS: Negative clamped to 0, out-of-bounds clamped to max index (3)")

    # -------------------------------------------------------------
    # TEST 14: Corrupted storage recovery
    # -------------------------------------------------------------
    print("\n[TEST 14] Corrupted storage recovery...")
    corrupted_data_list = [
        None,
        "not a dictionary",
        {},
        {"session_id": "bad"},
        {"questions": []},
        {"questions": "not a list"},
    ]
    for bad in corrupted_data_list:
        res = InterviewSessionState.restore_safely(bad)
        assert res is None, f"Expected None for corrupted data {bad}, got {res}"
    print("  PASS: Corrupted/malformed data safely returned None without crashing")

    # -------------------------------------------------------------
    # TEST 15: Active session restoration
    # -------------------------------------------------------------
    print("\n[TEST 15] Active session restoration from serialized state...")
    serialized = session.model_dump()
    restored = InterviewSessionState.restore_safely(serialized)
    assert restored is not None
    assert restored.session_id == session.session_id
    assert restored.current_question_index == 1
    assert len(restored.answers) == 2
    assert restored.status == "active"
    print("  PASS: Active session perfectly restored from serialized dictionary")

    # -------------------------------------------------------------
    # TEST 16: Refresh recovery simulation
    # -------------------------------------------------------------
    print("\n[TEST 16] Refresh recovery simulation at Question 2...")
    # In Question 2, candidate refreshes browser.
    # Restored state must maintain Question 2, previous Question 1 answer, and timing.
    refresh_recovered = InterviewSessionState.restore_safely(serialized)
    assert refresh_recovered.get_current_question().id == "q2"
    assert refresh_recovered.answers[0].question_id == "q1"
    assert refresh_recovered.answers[0].answer.startswith("Updated answer:")
    assert refresh_recovered.current_question_started_at == session.current_question_started_at
    print("  PASS: Refresh simulation restored current question 'q2', answered 'q1', and start timestamp")

    # -------------------------------------------------------------
    # TEST 17: Final-question completion transition
    # -------------------------------------------------------------
    print("\n[TEST 17] Question advancement through final question...")
    # Advance to Q3 (index 2)
    session.advance_question(timestamp=t0 + 30000)
    assert session.current_question_index == 2
    session.add_or_update_answer(
        question_id="q3",
        answer_text="I prioritize tasks using impact vs urgency and communicate early.",
        submitted_at=t0 + 40000,
        started_at=t0 + 30000,
        time_spent=10,
    )

    # Advance to Q4 (index 3 - final question)
    session.advance_question(timestamp=t0 + 41000)
    assert session.current_question_index == 3
    assert session.get_current_question().id == "q4"

    # Answer Q4
    session.add_or_update_answer(
        question_id="q4",
        answer_text="I read the official tutorial, build a CLI project, and write unit tests.",
        submitted_at=t0 + 55000,
        started_at=t0 + 41000,
        time_spent=14,
    )

    # Attempting to advance past index 3 must return False
    can_advance_further = session.advance_question(timestamp=t0 + 56000)
    assert can_advance_further is False
    assert session.current_question_index == 3
    print("  PASS: Final question reached; further advancement correctly returned False")

    # -------------------------------------------------------------
    # TEST 18: Completed session state
    # -------------------------------------------------------------
    print("\n[TEST 18] Completed session state...")
    t_complete = t0 + 57000
    session.complete_session(timestamp=t_complete)
    assert session.status == "completed"
    assert session.completed_at == t_complete
    assert len(session.answers) == 4
    assert len(session.questions) == 4
    progress_final = session.get_progress()
    assert progress_final.progress_percent == 100
    assert progress_final.remaining_count == 0
    print(f"  PASS: Session completed at {t_complete} with status='completed' and progress=100%")

    # -------------------------------------------------------------
    # TEST 19: No data loss after refresh
    # -------------------------------------------------------------
    print("\n[TEST 19] No data loss after refresh on completed state...")
    final_dump = session.model_dump()
    restored_final = InterviewSessionState.restore_safely(final_dump)
    assert restored_final is not None
    assert restored_final.status == "completed"
    assert restored_final.completed_at == t_complete
    assert len(restored_final.answers) == 4
    assert restored_final.answers[0].question_id == "q1"
    assert restored_final.answers[1].question_id == "q2"
    assert restored_final.answers[2].question_id == "q3"
    assert restored_final.answers[3].question_id == "q4"
    assert restored_final.answers[1].skipped is True
    print("  PASS: All 4 question records, answers, and skip metadata intact across serialization")

    # -------------------------------------------------------------
    # TEST 20: Existing Phase 7 generated question structure preserved
    # -------------------------------------------------------------
    print("\n[TEST 20] Existing Phase 7 question structure preserved...")
    for q in restored_final.questions:
        assert hasattr(q, "id") and q.id in ("q1", "q2", "q3", "q4")
        assert hasattr(q, "question") and len(q.question) > 10
        assert hasattr(q, "category") and q.category in ("Technical", "HR")
        assert hasattr(q, "topic")
        assert hasattr(q, "difficulty")
        assert hasattr(q, "focus")
        assert hasattr(q, "expected_aspects") and len(q.expected_aspects) >= 1
    print("  PASS: All Phase 7 schema fields and constraints 100% preserved")

    print("\n=================================================================")
    print("ALL 20 PHASE 8 AUTOMATED TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")


if __name__ == "__main__":
    run_all_tests()
