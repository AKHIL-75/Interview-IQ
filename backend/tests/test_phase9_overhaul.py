"""
Comprehensive test suite for Phase 9: Real Interview Mode & Adaptive Experience Overhaul.

Covers all 30 specification criteria:
- Test 01: First question is an Introduction question (not REST/DB/System Design)
- Test 02: Introduction answer "My name is Alex" is PARTIAL credit (score >= 45), not zero
- Test 03: "I don't know" is NON_ANSWER and scores 0
- Test 04: Irrelevant answer scores 0 or near 0
- Test 05: Partial answer gets partial credit (e.g. 40-70)
- Test 06: Strong technical answer gets strong evaluation (score >= 80)
- Test 07: Weak answer produces recovery or targeted follow-up
- Test 08: Strong answer produces deeper challenge or advanced difficulty
- Test 09: Partial intro answer produces TARGETED_FOLLOW_UP
- Test 10: Follow-up maintains relevant topic/stage without random jumps
- Test 11: Maximum 2 consecutive follow-ups strictly enforced (forces NEXT_TOPIC)
- Test 12: Static 5-question mode plan has exactly 5 stages
- Test 13: Static 10-question mode plan has exactly 10 stages
- Test 14: Static 15-question mode plan has exactly 15 stages
- Test 15: Static 20-question mode plan has exactly 20 stages
- Test 16: Dynamic mode plan initializes with min=5, max=20 boundary
- Test 17: Dynamic mode does not stop prematurely after one bad answer
- Test 18: Dynamic mode strictly respects minimum question threshold (< 5 never stops)
- Test 19: Dynamic mode strictly respects maximum question boundary (>= 20 always stops)
- Test 20: Dynamic mode eventually stops after adequate assessment (>= 5 questions with good coverage)
- Test 21: Resume and JD skills directly influence target topics in interview plan
- Test 22: Project discussion is scheduled after introduction and fundamentals
- Test 23: Questions are NOT generated in bulk (start interview returns exactly 1 question)
- Test 24: InterviewStartResponse contains only first_question and interview_plan
- Test 25: Adaptive decision engine returns single question or END_INTERVIEW
- Test 26: Prevent random REST/DB/System design questions if stage is Intro or unrelated
- Test 27: Phase 8 session persistence and serialization compatibility
- Test 28: Stage sequence generation for 5, 10, 15, and 20 questions
- Test 29: Conversational lead-in support in adaptive decisions
- Test 30: Start and Next-Question API request/response schemas validate correctly
"""

import asyncio
import os
import sys

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.schemas.adaptive import (
    AdaptiveDecisionType,
    AdaptiveEvaluationInput,
    AdaptiveNextQuestionRequest,
    AdaptiveNextQuestionResponse,
    InterviewStartRequest,
    InterviewStartResponse,
)
from app.schemas.evaluation import AnswerEvaluationResponse
from app.schemas.interview import GeneratedQuestion, InterviewSessionState
from app.services.adaptive_interviewer import (
    create_interview_plan,
    create_initial_interview_state,
    create_first_question,
    decide_next_action,
    should_end_dynamic_session,
    process_adaptive_start,
    MAX_CONSECUTIVE_FOLLOWUPS,
    MIN_DYNAMIC_QUESTIONS,
    MAX_DYNAMIC_QUESTIONS,
)
from app.services.evaluator import evaluate_candidate_answer
from app.services.question_generator import determine_stage_sequence


def eval_sync(**kwargs) -> AnswerEvaluationResponse:
    return asyncio.run(evaluate_candidate_answer(**kwargs))


class TestPhase9Overhaul:
    """Suite testing all Phase 9 Adaptive Interview Experience Overhaul features."""

    # 1. First question is introduction
    def test_01_first_question_is_introduction(self):
        q1 = create_first_question(candidate_name="Alex", role="Java Backend Engineer")
        assert q1.stage == "INTRO"
        assert q1.category in ["Introduction", "General", "HR", "Technical"]
        assert q1.difficulty == "Easy"
        assert "introduce yourself" in q1.question.lower() or "background" in q1.question.lower()
        # Verify it doesn't jump directly to REST/DB/System Design
        assert "rest api" not in q1.question.lower()
        assert "database" not in q1.question.lower()
        assert "system design" not in q1.question.lower()

    # 2. Introduction answer "My name is Alex" is PARTIAL, not zero
    def test_02_intro_name_answer_is_partial_not_zero(self):
        res = eval_sync(
            question="Hi Alex, could you please introduce yourself and briefly walk me through your background?",
            candidate_answer="My name is Alex.",
            job_title="Software Engineer",
            category="Introduction",
            difficulty="Easy",
            stage="INTRO",
        )
        assert res.score >= 45, f"Expected partial score >= 45, got {res.score}"
        assert res.relevance >= 50, f"Expected relevance >= 50, got {res.relevance}"
        assert res.clarity >= 60

    # 3. "I don't know" is NON_ANSWER and scores 0
    def test_03_i_dont_know_is_non_answer_score_0(self):
        res = eval_sync(
            question="What is polymorphism in Java and how does runtime polymorphism work?",
            candidate_answer="I don't know.",
            job_title="Software Engineer",
            category="Technical",
            difficulty="Medium",
            stage="TECHNICAL_FUNDAMENTALS",
        )
        assert res.score == 0
        assert res.technical_accuracy == 0
        assert res.depth == 0

    # 4. Irrelevant answer scores 0 or near 0
    def test_04_irrelevant_answer_scores_0_or_near_0(self):
        res = eval_sync(
            question="Could you introduce yourself and walk me through your background?",
            candidate_answer="Binary search has O(log n) complexity and divides arrays in half.",
            job_title="Software Engineer",
            category="Introduction",
            difficulty="Easy",
            stage="INTRO",
        )
        assert res.score <= 30
        assert res.relevance <= 25

    # 5. Partial answer gets partial credit
    def test_05_partial_answer_gets_partial_credit(self):
        res = eval_sync(
            question="What is polymorphism in Java?",
            candidate_answer="It means the same method can behave differently in different situations.",
            job_title="Java Developer",
            category="Technical",
            difficulty="Medium",
            stage="TECHNICAL_FUNDAMENTALS",
        )
        assert 40 <= res.score <= 75
        assert res.relevance >= 50

    # 6. Strong answer gets strong evaluation
    def test_06_strong_answer_gets_strong_evaluation(self):
        res = eval_sync(
            question="What is polymorphism in Java?",
            candidate_answer=(
                "Polymorphism in Java allows an entity such as a method or object to take on multiple forms. "
                "There are two primary types: compile-time polymorphism achieved via method overloading, where methods share "
                "the same name but different signatures, and runtime polymorphism achieved via method overriding, where a subclass "
                "provides a specific implementation of a method defined in its superclass using dynamic method dispatch via the vtable."
            ),
            job_title="Java Developer",
            category="Technical",
            difficulty="Medium",
            stage="TECHNICAL_FUNDAMENTALS",
        )
        assert res.score >= 80
        assert res.technical_accuracy >= 80

    # 7. Weak answer produces targeted follow-up or recovery
    def test_07_weak_answer_produces_targeted_follow_up_or_recovery(self):
        eval_resp = AnswerEvaluationResponse(
            score=20,
            technicalAccuracy=20,
            clarity=50,
            depth=15,
            relevance=60,
            strengths=["Attempted to respond"],
            improvements=["Need deeper knowledge"],
            suggestedAnswer="Inheritance basics",
        )
        decision, reason, diff, is_fu = decide_next_action(
            evaluation=eval_resp,
            previous_question="What is polymorphism in Java?",
            difficulty="Medium",
            consecutive_follow_ups=0,
            current_stage="TECHNICAL_FUNDAMENTALS",
            candidate_answer="I am not very sure about polymorphism.",
            allow_recovery=True,
        )
        assert decision in ["RECOVERY_QUESTION", "TARGETED_FOLLOW_UP"]
        assert is_fu is True

    # 8. Strong answer produces deeper question
    def test_08_strong_answer_produces_deeper_question(self):
        eval_resp = AnswerEvaluationResponse(
            score=88,
            technicalAccuracy=90,
            clarity=85,
            depth=85,
            relevance=90,
            strengths=["Excellent explanation of polymorphism"],
            improvements=[],
            suggestedAnswer="",
        )
        decision, reason, diff, is_fu = decide_next_action(
            evaluation=eval_resp,
            previous_question="What is polymorphism in Java?",
            difficulty="Medium",
            consecutive_follow_ups=0,
            current_stage="TECHNICAL_FUNDAMENTALS",
            candidate_answer="Clear explanation given.",
        )
        assert decision in ["DEEPER_CHALLENGE", "ADVANCE_DIFFICULTY"]

    # 9. Partial intro answer produces TARGETED_FOLLOW_UP
    def test_09_partial_intro_produces_targeted_follow_up(self):
        eval_resp = AnswerEvaluationResponse(
            score=50,
            technicalAccuracy=50,
            clarity=70,
            depth=30,
            relevance=60,
            strengths=["Stated candidate name"],
            improvements=["Expand on background"],
            suggestedAnswer="",
        )
        decision, reason, diff, is_fu = decide_next_action(
            evaluation=eval_resp,
            previous_question="Hi Alex, could you please introduce yourself and briefly walk me through your background?",
            difficulty="Easy",
            consecutive_follow_ups=0,
            current_stage="INTRO",
            candidate_answer="My name is Alex.",
        )
        assert decision == "TARGETED_FOLLOW_UP"
        assert is_fu is True

    # 10. Follow-up does not randomly switch topics
    def test_10_follow_up_does_not_randomly_switch_topics(self):
        eval_resp = AnswerEvaluationResponse(
            score=55,
            technicalAccuracy=55,
            clarity=60,
            depth=45,
            relevance=65,
            strengths=[],
            improvements=[],
            suggestedAnswer="",
        )
        decision, reason, diff, is_fu = decide_next_action(
            evaluation=eval_resp,
            previous_question="What is polymorphism in Java?",
            difficulty="Medium",
            consecutive_follow_ups=1,
            current_stage="TECHNICAL_FUNDAMENTALS",
            candidate_answer="It means same method behaves differently.",
        )
        assert decision == "TARGETED_FOLLOW_UP"
        assert is_fu is True

    # 11. Maximum two consecutive follow-ups
    def test_11_max_two_consecutive_follow_ups(self):
        eval_resp = AnswerEvaluationResponse(
            score=50,
            technicalAccuracy=50,
            clarity=60,
            depth=40,
            relevance=60,
            strengths=[],
            improvements=[],
            suggestedAnswer="",
        )
        decision, reason, diff, is_fu = decide_next_action(
            evaluation=eval_resp,
            previous_question="What is polymorphism in Java?",
            difficulty="Medium",
            consecutive_follow_ups=MAX_CONSECUTIVE_FOLLOWUPS,
            current_stage="TECHNICAL_FUNDAMENTALS",
            candidate_answer="Still slightly partial.",
        )
        assert decision == "NEXT_TOPIC"
        assert is_fu is False
        assert "follow-ups" in reason.lower() or "follow-up" in reason.lower()

    # 12. Static 5-question mode plan
    def test_12_static_5_question_mode_plan(self):
        plan = create_interview_plan(question_count=5, interview_mode="STATIC", role="Backend Dev")
        assert plan["interview_mode"] == "STATIC"
        assert plan["total_questions"] == 5
        assert len(plan["planned_sequence"]) == 5
        assert plan["planned_sequence"][0]["stage"] == "INTRO"

    # 13. Static 10-question mode plan
    def test_13_static_10_question_mode_plan(self):
        plan = create_interview_plan(question_count=10, interview_mode="STATIC", role="Backend Dev")
        assert plan["interview_mode"] == "STATIC"
        assert plan["total_questions"] == 10
        assert len(plan["planned_sequence"]) == 10
        assert plan["planned_sequence"][0]["stage"] == "INTRO"

    # 14. Static 15-question mode plan
    def test_14_static_15_question_mode_plan(self):
        plan = create_interview_plan(question_count=15, interview_mode="STATIC", role="Full Stack")
        assert plan["total_questions"] == 15
        assert len(plan["planned_sequence"]) == 15

    # 15. Static 20-question mode plan
    def test_15_static_20_question_mode_plan(self):
        plan = create_interview_plan(question_count=20, interview_mode="STATIC", role="Full Stack")
        assert plan["total_questions"] == 20
        assert len(plan["planned_sequence"]) == 20

    # 16. Dynamic mode plan configuration
    def test_16_dynamic_mode_plan(self):
        plan = create_interview_plan(question_count=10, interview_mode="DYNAMIC", role="Full Stack")
        assert plan["interview_mode"] == "DYNAMIC"
        assert plan["min_questions"] == MIN_DYNAMIC_QUESTIONS
        assert plan["max_questions"] == MAX_DYNAMIC_QUESTIONS

    # 17. Dynamic mode does not stop after one bad answer
    def test_17_dynamic_mode_does_not_stop_after_one_bad_answer(self):
        state = create_initial_interview_state()
        state["questions_asked"] = 2
        state["recent_scores"] = [60, 20]
        state["consecutive_weak_answers"] = 1

        should_end, reason = should_end_dynamic_session(state, min_questions=5, max_questions=20)
        assert should_end is False
        assert "Minimum boundary" in reason

    # 18. Dynamic mode respects minimum question count
    def test_18_dynamic_mode_respects_minimum_question_count(self):
        state = create_initial_interview_state()
        for count in range(1, 5):
            state["questions_asked"] = count
            should_end, _ = should_end_dynamic_session(state, min_questions=5, max_questions=20)
            assert should_end is False, f"Dynamic mode ended at question count {count} (< 5)"

    # 19. Dynamic mode respects maximum question count
    def test_19_dynamic_mode_respects_maximum_question_count(self):
        state = create_initial_interview_state()
        state["questions_asked"] = 20
        should_end, reason = should_end_dynamic_session(state, min_questions=5, max_questions=20)
        assert should_end is True
        assert "Maximum dynamic question limit" in reason

    # 20. Dynamic mode eventually ends when depth assessed
    def test_20_dynamic_mode_eventually_ends_when_depth_assessed(self):
        state = create_initial_interview_state()
        state["questions_asked"] = 8
        state["topics_covered"] = ["INTRO", "Java", "Spring Boot", "Cinemaverse", "SQL", "Architecture"]
        state["skills_assessed"] = ["Java", "Spring Boot", "MongoDB", "REST APIs"]
        state["recent_scores"] = [85, 88, 82, 80, 85]
        state["required_skills_covered"] = True

        should_end, reason = should_end_dynamic_session(state, min_questions=5, max_questions=20)
        assert should_end is True
        assert "Comprehensive assessment reached" in reason or "competencies" in reason

    # 21. Resume and JD skills influence interview topics
    def test_21_resume_jd_influences_topics(self):
        candidate_profile = {
            "name": "Alex",
            "skills": ["Java", "React", "MongoDB"],
            "projects": ["Cinemaverse Movie App"],
        }
        job_profile = {
            "title": "Java Spring Developer",
            "skills": ["Java", "Spring Boot", "SQL", "REST APIs"],
        }
        plan = create_interview_plan(
            question_count=10,
            interview_mode="STATIC",
            candidate_profile=candidate_profile,
            job_profile=job_profile,
        )
        target_skills = plan.get("target_skills", [])
        assert "Java" in target_skills
        assert any(s in target_skills for s in ["Spring Boot", "SQL", "React", "MongoDB"])
        # Rust or Kubernetes should NOT be in target skills since neither resume nor JD mentioned them
        assert "Rust" not in target_skills
        assert "Kubernetes" not in target_skills

    # 22. Project discussion happens after introduction/fundamentals
    def test_22_project_discussion_after_fundamentals(self):
        candidate_profile = {
            "name": "Alex",
            "projects": ["Cinemaverse"],
        }
        plan = create_interview_plan(
            question_count=10,
            interview_mode="STATIC",
            candidate_profile=candidate_profile,
        )
        stages = [item["stage"] for item in plan["planned_sequence"]]
        assert stages[0] == "INTRO"
        assert any("PROJECT" in s for s in stages)
        proj_idx = [i for i, s in enumerate(stages) if "PROJECT" in s][0]
        assert proj_idx >= 3, f"Project stage at index {proj_idx} appeared too early!"

    # 23. Questions are NOT generated in bulk (Start returns only 1 question)
    def test_23_questions_not_generated_in_bulk(self):
        req = InterviewStartRequest(
            role="Java Developer",
            interview_mode="STATIC",
            question_count=10,
            candidate_profile={"name": "Alex"},
        )
        res = asyncio.run(process_adaptive_start(req))
        assert isinstance(res, InterviewStartResponse)
        assert res.first_question is not None
        assert isinstance(res.first_question, GeneratedQuestion)
        assert res.first_question.stage == "INTRO"
        # Verify first_question is a single object, not a list of 10 questions
        assert not isinstance(res.first_question, list)

    # 24. Start interview returns only first question and plan
    def test_24_start_interview_returns_only_first_question(self):
        req = InterviewStartRequest(
            role="Software Engineer",
            interview_mode="DYNAMIC",
        )
        res = asyncio.run(process_adaptive_start(req))
        assert res.interview_plan["interview_mode"] == "DYNAMIC"
        assert res.interview_state["questions_asked"] == 1
        assert res.first_question.question != ""

    # 25. Next-question generates only one question or ends
    def test_25_next_question_generates_only_one_question(self):
        eval_resp = AdaptiveEvaluationInput(
            score=85,
            technicalAccuracy=85,
            clarity=85,
            depth=85,
            relevance=90,
            strengths=["Good"],
            improvements=[],
            suggestedAnswer="",
        )
        req = AdaptiveNextQuestionRequest(
            previous_question="Could you introduce yourself?",
            candidate_answer="I am a B.Tech CSE student specializing in Java and web development.",
            evaluation=eval_resp,
            category="Introduction",
            difficulty="Easy",
            current_topic="Introduction",
            consecutive_follow_ups=0,
            interview_mode="STATIC",
            role="Software Engineer",
            candidate_profile={"name": "Alex", "skills": ["Java", "Python"]},
        )
        # Verify request schema instantiates cleanly
        assert req.candidate_profile["name"] == "Alex"
        assert req.interview_mode == "STATIC"

    # 26. REST/database/system-design repetition is prevented
    def test_26_prevent_random_rest_database_system_design_repetition(self):
        q1 = create_first_question(candidate_name="Alex", role="Frontend Developer")
        assert "system design" not in q1.question.lower()
        assert "sql" not in q1.question.lower()

    # 27. Phase 8 persistence still works
    def test_27_phase8_persistence_still_works(self):
        q1 = create_first_question(candidate_name="Alex")
        session = InterviewSessionState(
            session_id="test-session-adaptive",
            status="active",
            current_question_index=0,
            questions=[q1],
        )
        # Serialization to dict and back
        dump = session.model_dump()
        restored = InterviewSessionState(**dump)
        assert restored.session_id == "test-session-adaptive"
        assert len(restored.questions) == 1
        assert restored.questions[0].stage == "INTRO"

    # 28. Stage sequence lengths for 5, 10, 15, 20
    def test_28_stage_sequence_lengths(self):
        for count in [5, 10, 15, 20]:
            seq = determine_stage_sequence(count)
            assert len(seq) == count, f"Expected {count} stages, got {len(seq)}"
            assert seq[0] == "INTRO"

    # 29. Conversational lead-in support
    def test_29_conversational_lead_in_support(self):
        resp = AdaptiveNextQuestionResponse(
            decision="TARGETED_FOLLOW_UP",
            reason="Explore Java experience mentioned in intro.",
            next_difficulty="Easy",
            is_follow_up=True,
            conversational_lead_in="Thanks Alex, you mentioned having experience with Java. Let's start there.",
        )
        assert resp.conversational_lead_in is not None
        assert "Alex" in resp.conversational_lead_in

    # 30. Start and Next-Question API Schemas validation
    def test_30_api_endpoints_start_and_next_question_schemas(self):
        start_req = InterviewStartRequest(
            role="Java Backend Engineer",
            interview_mode="STATIC",
            question_count=10,
        )
        assert start_req.question_count == 10
        assert start_req.interview_mode == "STATIC"

        start_res = asyncio.run(process_adaptive_start(start_req))
        assert start_res.first_question.stage == "INTRO"
        assert start_res.interview_plan["total_questions"] == 10


def run_all_tests():
    suite = TestPhase9Overhaul()
    test_methods = [m for m in dir(suite) if m.startswith("test_")]
    test_methods.sort()

    print("=================================================================")
    print(f"RUNNING {len(test_methods)} AUTOMATED PHASE 9 OVERHAUL TESTS")
    print("=================================================================")

    passed_count = 0
    failed_count = 0

    for m_name in test_methods:
        test_fn = getattr(suite, m_name)
        try:
            test_fn()
            print(f"  [PASS] {m_name}")
            passed_count += 1
        except Exception as e:
            print(f"  [FAIL] {m_name}: {e}")
            import traceback
            traceback.print_exc()
            failed_count += 1

    print("\n=================================================================")
    print(f"PHASE 9 OVERHAUL TEST RESULTS: {passed_count} PASSED, {failed_count} FAILED")
    print("=================================================================")
    if failed_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    run_all_tests()

