"""Scoped interview contracts with controlled model/DB outputs, no fabricated live scores."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError
from app.schemas.adaptive import InterviewStartRequest, AdaptiveNextQuestionRequest
from app.schemas.interview import QuestionGenerationRequest
from app.services import adaptive_interviewer as engine, interview_commit as commit
from app.services.question_generator import generate_interview_questions
from app.services.report_generator import generate_final_report, normalize_report_for_response
from app.services.question_policy import semantic_duplicate, SUBJECT_TOPICS


def evaluation(score=90, status="CORRECT"):
    return dict(score=score, technicalAccuracy=score, relevance=score, depth=score, clarity=score, answer_status=status)


class SubjectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.model = AsyncMock(return_value={"question": "How do Java interfaces describe a contract?", "lead_in": "Let's explore another concept."})
        p = patch.object(engine.llm_service, 'generate_json_response', self.model)
        p.start(); self.addCleanup(p.stop)
        p = patch.object(engine, 'semantic_duplicate', return_value=False)
        p.start(); self.addCleanup(p.stop)

    async def start(self, subject="Java", **kw):
        return await engine.process_adaptive_start(InterviewStartRequest(subject=subject, **kw))

    def next_request(self, started, score=90, **kw):
        return AdaptiveNextQuestionRequest(previous_question="What is a Java primitive type?", candidate_answer="An int stores a whole number.",
            evaluation=evaluation(score), interview_plan=started.interview_plan, interview_state=started.interview_state,
            current_topic="Java types and variables", relevant_skills=["Java types and variables"],
            question_history=["What is a Java primitive type?"], **kw)

    async def test_java_and_oop_open_with_subject_not_resume(self):
        for subject, question in [("Java", "What is the role of the JVM in Java?"), ("OOP", "What is encapsulation in object-oriented programming?")]:
            with self.subTest(subject=subject):
                self.model.return_value = {"question": question}
                result = await self.start(subject, candidate_profile={"candidate_name": "Example", "skills": ["SQL"]}, difficulty="Hard")
                self.assertEqual(result.first_question.question, question)
                self.assertEqual(result.first_question.stage, "TECHNICAL_FUNDAMENTALS")
                self.assertEqual(result.first_question.difficulty, "Medium")
                self.assertEqual(result.interview_plan["subject"], subject)
                self.assertIn(f"FIXED SUBJECT: {subject}", self.model.call_args.kwargs["prompt"])
                self.assertNotIn("SQL", result.interview_plan["skills_priority"])

    async def test_general_has_one_opening_even_with_weak_intro(self):
        start = await self.start(None, candidate_profile={"candidate_name": "Example"})
        self.assertIn("Hi Example", start.first_question.question)
        self.assertNotIn("RESUME_BACKGROUND", start.interview_plan["stages_planned"])
        request = self.next_request(start, score=20)
        request.previous_question = start.first_question.question
        request.current_topic = "Candidate Introduction"
        request.candidate_answer = "My name is Example"
        result = await engine.process_adaptive_next_question(request)
        self.assertEqual(result.decision, "NEXT_TOPIC")
        self.assertNotEqual(result.question.stage, "INTRO")
        self.assertNotIn("Alex", result.question.question)

    async def test_old_plan_skips_background_without_reset(self):
        start = await self.start(None)
        start.interview_plan["stages_planned"] = ["INTRO", "RESUME_BACKGROUND", "TECHNICAL_FUNDAMENTALS"]
        result = await engine.process_adaptive_next_question(self.next_request(start, 60))
        self.assertEqual(result.interview_plan["current_stage_index"], 2)
        self.assertEqual(result.interview_state["questions_asked"], 2)

    async def test_weak_reduces_one_level_partial_holds_missing_holds(self):
        start = await self.start()
        for score, expected in [(20, "Easy"), (60, "Medium")]:
            result = await engine.process_adaptive_next_question(self.next_request(start, score))
            self.assertEqual(result.question.difficulty, expected)
            self.assertEqual(result.nextDifficulty, expected)
            self.assertEqual(result.interview_state["current_difficulty"], expected)
            self.assertEqual(result.interview_plan["subject"], "Java")
        for ev in [None, {}, {"score": 95}, evaluation(0, "FAILED")]:
            request = self.next_request(start)
            request = request.model_copy(update={"evaluation": None}) if ev is None else AdaptiveNextQuestionRequest(**{**request.model_dump(), "evaluation": ev})
            result = await engine.process_adaptive_next_question(request)
            self.assertEqual(result.question.difficulty, "Medium")
            self.assertIn("unavailable", result.reason)

    async def test_strong_progression_survives_serialization_no_single_answer_jump(self):
        start = await self.start(difficulty="Easy")
        request = self.next_request(start)
        first = await engine.process_adaptive_next_question(request)
        self.assertEqual(first.question.difficulty, "Easy")
        request = AdaptiveNextQuestionRequest(**{**request.model_dump(), "interview_state": first.interview_state, "interview_plan": first.interview_plan})
        second = await engine.process_adaptive_next_question(request)
        self.assertEqual(second.question.difficulty, "Medium")
        request.interview_state = second.interview_state
        third = await engine.process_adaptive_next_question(request)
        self.assertEqual(third.question.difficulty, "Medium")
        request.interview_state = third.interview_state
        fourth = await engine.process_adaptive_next_question(request)
        self.assertEqual(fourth.question.difficulty, "Hard")

    async def test_repeated_weak_returns_to_fundamentals_with_followup_limit(self):
        start = await self.start()
        start.interview_state["current_difficulty"] = "Hard"
        req = self.next_request(start, 10, consecutive_follow_ups=2)
        result = await engine.process_adaptive_next_question(req)
        self.assertEqual(result.decision, "NEXT_TOPIC")
        self.assertEqual(result.question.difficulty, "Medium")
        req.interview_state = result.interview_state
        result = await engine.process_adaptive_next_question(req)
        self.assertEqual(result.question.difficulty, "Easy")
        self.assertEqual(result.interview_plan["subject"], "Java")

    async def test_prompt_contains_full_question_history_answers_and_feedback(self):
        start = await self.start()
        req = self.next_request(start, 60, answer_history=[{"question": "Earlier question", "answer": "Earlier answer", "evaluation": {"score": 50}}])
        req.question_history = [f"Old question {i}" for i in range(10)]
        req.evaluation.answer_status = "PARTIAL"
        req.evaluation.improvements = ["Explain the type distinction"]
        req.evaluation.suggestedAnswer = "PRIVATE_EXPECTED_ANSWER"
        await engine.process_adaptive_next_question(req)
        prompt = self.model.call_args.kwargs["prompt"]
        for text in ["Old question 0", "Old question 9", req.previous_question, "Earlier answer", "Explain the type distinction", "basic problem", "Never include the expected answer"]:
            self.assertIn(text, prompt)
        self.assertNotIn("PRIVATE_EXPECTED_ANSWER", prompt)

    async def test_rejects_openings_unrelated_and_semantic_duplicates_with_bounded_retry(self):
        for bad in ["Tell me about your educational background?", "How does a SQL query use indexes?"]:
            self.model.side_effect = [{"question": bad}] * engine.MAX_GENERATION_RETRIES + [{"question": "What is a Java primitive type?"}]
            result = await self.start()
            self.assertEqual(result.first_question.question, "What is a Java primitive type?")
        self.model.side_effect = None
        started = await self.start()
        with patch.object(engine, "semantic_duplicate", return_value=True):
            with self.assertRaises(engine.LLMResponseParseError):
                await engine.process_adaptive_next_question(self.next_request(started))

    async def test_generation_failure_does_not_mutate_input_state(self):
        start = await self.start()
        req = self.next_request(start)
        before = copy.deepcopy(req.model_dump())
        self.model.side_effect = engine.OllamaConnectionError("offline")
        with self.assertRaises(engine.OllamaConnectionError):
            await engine.process_adaptive_next_question(req)
        self.assertEqual(req.model_dump(), before)

    async def test_dynamic_minimum_and_completion_do_not_require_intro(self):
        start = await self.start(interview_mode="DYNAMIC")
        req = self.next_request(start, 60)
        req.interview_state.update(questions_asked=5, recent_scores=[60]*4, covered_topics=SUBJECT_TOPICS["Java"][:3])
        result = await engine.process_adaptive_next_question(req)
        self.assertTrue(result.end_interview)
        req.interview_state["questions_asked"] = 4
        self.assertFalse((await engine.process_adaptive_next_question(req)).end_interview)

    async def test_start_endpoint_persists_subject_in_existing_json(self):
        from app.api.v1.endpoints import interview
        request = InterviewStartRequest(subject="Java")
        with patch.object(interview, "persist_interview_session", AsyncMock(return_value={"id": "db-session"})) as save, patch.object(interview, "persist_interview_question", AsyncMock(return_value={"id": "db-q1"})):
            response = await interview.start_interview(request, SimpleNamespace(user_id="owner", token="owner-token"))
        self.assertEqual(save.call_args.kwargs["interview_config"]["subject"], "Java")
        self.assertEqual(save.call_args.kwargs["interview_state"]["subject"], "Java")
        self.assertEqual(response.interview_plan["subject"], "Java")

    async def test_partial_status_never_promotes_even_with_high_scores(self):
        start = await self.start()
        start.interview_state["consecutive_strong_answers"] = 1
        request = self.next_request(start)
        request.evaluation.answer_status = "PARTIAL"
        result = await engine.process_adaptive_next_question(request)
        self.assertEqual(result.question.difficulty, "Medium")
        self.assertEqual(result.interview_state["consecutive_strong_answers"], 0)

    async def test_explicit_background_configuration_preserves_optional_followup(self):
        start = await self.start(None)
        start.interview_plan["allow_background_follow_up"] = True
        request = self.next_request(start, 20)
        request.previous_question = start.first_question.question
        request.current_topic = "Candidate Introduction"
        request.candidate_answer = "My name is Example"
        self.model.return_value = {"question": "Can you describe your educational background?"}
        result = await engine.process_adaptive_next_question(request)
        self.assertEqual(result.decision, "TARGETED_FOLLOW_UP")

    async def test_subject_start_failure_is_retryable_and_never_saved_as_intro(self):
        from fastapi import HTTPException
        from app.api.v1.endpoints import interview
        self.model.side_effect = engine.LLMResponseParseError("invalid output")
        with patch.object(interview, "persist_interview_session", AsyncMock()) as save:
            with self.assertRaises(HTTPException) as caught:
                await interview.start_interview(InterviewStartRequest(subject="Java"), SimpleNamespace(user_id="owner", token="owner-token"))
        self.assertEqual(caught.exception.status_code, 502)
        save.assert_not_awaited()
        self.assertEqual(self.model.await_count, engine.MAX_GENERATION_RETRIES + 1)

    async def test_legacy_bulk_subject_uses_scoped_generation(self):
        request = QuestionGenerationRequest(candidate_profile={}, job_profile={}, subject="Java", question_count=1)
        response = await generate_interview_questions(request)
        self.assertEqual(response.count, 1)
        self.assertNotEqual(response.questions[0].stage, "INTRO")

    def test_validation_and_old_requests(self):
        self.assertIsNone(InterviewStartRequest().subject)
        for payload in [{"subject": "invalid"}, {"subject": "Java", "interview_type": "HR"}, {"subject": "OOP", "interview_type": "Mixed"}]:
            with self.assertRaises(ValidationError): InterviewStartRequest(**payload)

    def test_report_subject_survives_existing_scores_json(self):
        report = generate_final_report("test", "Engineer", "Technical", "Medium", [], [], interview_plan={"subject": "OOP"})
        restored = normalize_report_for_response({k: v for k, v in report.items() if k != "subject"})
        self.assertEqual(restored["subject"], "OOP")
        self.assertIsNone(normalize_report_for_response({"overall_score": 0})["subject"])

    def test_report_keeps_return_to_easier_level(self):
        from app.services.report_generator import build_adaptive_summary
        summary = build_adaptive_summary(None, None, [{"difficulty": d} for d in ["Easy", "Easy", "Medium", "Easy"]])
        self.assertEqual(summary["difficulty_progression"], "Easy → Medium → Easy")

    def test_semantic_encoder_detects_paraphrase(self):
        import numpy as np
        encoder = SimpleNamespace(encode=lambda *a, **k: np.array([[1., 0.], [.95, .1]]))
        import sys
        with patch.dict(sys.modules, {"app.services.semantic_matcher": SimpleNamespace(get_embedding_model=lambda: encoder)}):
            self.assertTrue(semantic_duplicate("What does encapsulation protect?", ["How does data hiding work?"]))


class StoredContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_commit_uses_saved_scope_scores_history_and_difficulty(self):
        session = dict(id="s", status="active", interview_type="Technical", interview_plan={"subject": "Java"}, interview_state={"current_difficulty": "Easy", "consecutive_follow_ups": 1})
        question = dict(id="dbq", question_id="q1", question_text="What is a Java type?", question_order=1, difficulty="Easy", topic="Java", category="Technical")
        answer = dict(question_id="dbq", answer_text="A type describes values", score=60, technical_accuracy=60, relevance=60, depth=60, clarity=60)
        async def rows(token, table, filters):
            return {"interview_sessions": [session], "interview_questions": [question], "candidate_answers": [answer]}[table]
        request = AdaptiveNextQuestionRequest(session_id="session", previous_question=question["question_text"], candidate_answer=answer["answer_text"],
            difficulty="Hard", interview_plan={"subject": "OOP"}, evaluation=evaluation(), answer_history=[{"questionId": "q1", "answer": "forged"}])
        from app.schemas.adaptive import AdaptiveNextQuestionResponse
        response = AdaptiveNextQuestionResponse(decision="END_INTERVIEW", reason="cap", end_interview=True)
        with patch.object(commit, 'read_owned_rows', side_effect=rows), patch.object(commit, 'update_interview_session', AsyncMock(return_value=True)), patch.object(commit, 'process_adaptive_next_question', AsyncMock(return_value=response)) as generate:
            await commit.commit_answer(request, SimpleNamespace(user_id="owner", token="owner-token"))
        saved = generate.call_args.args[0]
        self.assertEqual(saved.interview_plan["subject"], "Java")
        self.assertEqual(saved.difficulty, "Easy")
        self.assertEqual(saved.consecutive_follow_ups, 1)
        self.assertEqual(saved.evaluation.score, 60)
        self.assertEqual(saved.answer_history[0]["answer"], answer["answer_text"])

