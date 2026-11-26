"""Regression test for the third-question 502 bug.

Reproduces the exact failure: after two questions are in history, the next-question
generation fails because subject_matches rejects the model output and the duplicate
detector rejects the retry, exhausting the retry budget and producing a 502.

Verifies that:
1. The third question generates successfully with 2 questions in history.
2. Subject validation still rejects genuinely off-subject questions.
3. Duplicate detection still rejects identical questions.
4. The deterministic fallback is used when all LLM retries are exhausted.
5. Malformed model output is handled safely.
6. Retry exhaustion produces a controlled response rather than an unhandled failure.
"""
import unittest
from unittest.mock import AsyncMock, patch
from app.schemas.adaptive import AdaptiveNextQuestionRequest, InterviewStartRequest
from app.services import adaptive_interviewer as engine


VALID_JAVA_Q = {"question": "How do Java interfaces enable polymorphism?", "lead_in": "Let's explore."}
START_Q = {"question": "What is the role of the JVM in Java?"}


def evaluation(score=90, status="CORRECT"):
    return dict(score=score, technicalAccuracy=score, relevance=score,
                depth=score, clarity=score, answer_status=status)


class ThirdQuestionRegressionTest(unittest.IsolatedAsyncioTestCase):
    """Reproduces the exact 502 bug scenario and verifies the fix."""

    def setUp(self):
        self.model = AsyncMock(return_value=VALID_JAVA_Q)
        p = patch.object(engine.llm_service, 'generate_json_response', self.model)
        p.start(); self.addCleanup(p.stop)
        p = patch.object(engine, 'semantic_duplicate', return_value=False)
        p.start(); self.addCleanup(p.stop)

    async def _start_java(self):
        return await engine.process_adaptive_start(InterviewStartRequest(subject="Java"))

    def _next_request(self, started, history_count=2, **kw):
        """Build a request simulating `history_count` prior questions."""
        history = [f"Java question {i+1}?" for i in range(history_count)]
        state = dict(started.interview_state)
        state["questions_asked"] = history_count
        return AdaptiveNextQuestionRequest(
            previous_question=history[-1] if history else "What is Java?",
            candidate_answer="It stores a whole number.",
            evaluation=evaluation(60),
            interview_plan=started.interview_plan,
            interview_state=state,
            current_topic="Java types and variables",
            relevant_skills=["Java types and variables"],
            question_history=history,
            **kw,
        )

    # ── Scenario 1: Third question generates successfully ──
    async def test_third_question_succeeds_with_valid_model_output(self):
        """Previously this was the exact failure: history_count=2 → 502."""
        started = await self._start_java()
        request = self._next_request(started, history_count=2)
        result = await engine.process_adaptive_next_question(request)
        self.assertIsNotNone(result.question)
        self.assertEqual(result.question.category, "Technical")
        self.assertIn("Java", result.question.question)
        self.assertFalse(result.end_interview)

    # ── Scenario 2: Subject rejection on first attempt, success on retry ──
    async def test_subject_rejected_then_valid_on_retry(self):
        """Model returns off-subject question first, then a valid one."""
        # start_java uses 1 call, then next-question generation uses up to 4
        off_subject = {"question": "What is the difference between a stack and a queue?"}
        self.model.side_effect = [
            START_Q,  # for _start_java
            off_subject,  # attempt 0: fails subject_matches
            VALID_JAVA_Q,  # attempt 1: passes
        ]
        started = await self._start_java()
        request = self._next_request(started, history_count=2)
        result = await engine.process_adaptive_next_question(request)
        self.assertIsNotNone(result.question)
        self.assertIn("Java", result.question.question)

    # ── Scenario 3: All retries fail → deterministic fallback used ──
    async def test_all_retries_fail_uses_fallback(self):
        """When all LLM outputs fail validation, fallback question is returned."""
        off_subject = {"question": "What is a stack?"}
        self.model.side_effect = [START_Q] + [off_subject] * (engine.MAX_GENERATION_RETRIES + 1)
        started = await self._start_java()
        request = self._next_request(started, history_count=2)
        # The fallback should produce a valid question without raising
        result = await engine.process_adaptive_next_question(request)
        self.assertIsNotNone(result.question)
        self.assertEqual(result.question.category, "Technical")
        self.assertIsNotNone(result.question.topic)

    # ── Scenario 4: Genuine duplicate is still rejected ──
    async def test_duplicate_question_still_rejected_on_individual_attempt(self):
        """A question identical to one in history fails validation on that attempt."""
        started = await self._start_java()
        request = self._next_request(started, history_count=2)
        request.question_history = ["How do Java interfaces enable polymorphism?", "Another Java question?"]
        # Model returns exact duplicate of history[0], then a valid different question
        self.model.side_effect = [
            {"question": "How do Java interfaces enable polymorphism?"},  # Duplicate
            {"question": "What is the difference between ArrayList and LinkedList in Java?"},  # Valid
        ]
        result = await engine.process_adaptive_next_question(request)
        self.assertIsNotNone(result.question)
        self.assertNotEqual(result.question.question, "How do Java interfaces enable polymorphism?")

    # ── Scenario 5: Malformed model output handled safely ──
    async def test_malformed_output_handled_with_retries(self):
        """LLMResponseParseError on first attempt, valid on retry."""
        self.model.side_effect = [
            START_Q,  # for _start_java
            engine.LLMResponseParseError("invalid JSON"),  # attempt 0
            {"question": "What are Java generics and how do they ensure type safety?"},  # attempt 1
        ]
        started = await self._start_java()
        request = self._next_request(started, history_count=2)
        result = await engine.process_adaptive_next_question(request)
        self.assertIsNotNone(result.question)

    # ── Scenario 6: Complete LLM failure → fallback, not crash ──
    async def test_total_llm_failure_uses_fallback_not_crash(self):
        """All LLM calls raise parse error → fallback question is returned, not a 502."""
        # Need to let _start_java succeed first, then fail all subsequent calls
        started_data = None

        async def side_effect(*args, **kwargs):
            nonlocal started_data
            if started_data is None:
                return START_Q
            raise engine.LLMResponseParseError("always broken")

        self.model.side_effect = side_effect
        started = await self._start_java()
        started_data = True  # Now all subsequent calls will fail
        request = self._next_request(started, history_count=2)
        result = await engine.process_adaptive_next_question(request)
        self.assertIsNotNone(result.question)
        self.assertEqual(result.question.category, "Technical")

    # ── Scenario 7: Fourth and fifth questions also succeed ──
    async def test_fourth_and_fifth_questions_also_succeed(self):
        """Ensure the fix works beyond just the third question."""
        started = await self._start_java()
        for count in [3, 4]:
            with self.subTest(history_count=count):
                self.model.return_value = {"question": f"How does Java handle concurrency at level {count}?"}
                request = self._next_request(started, history_count=count)
                result = await engine.process_adaptive_next_question(request)
                self.assertIsNotNone(result.question)
                self.assertFalse(result.end_interview)

    # ── Scenario 8: Retry note includes specific rejection reason ──
    async def test_retry_prompt_includes_subject_rejection_reason(self):
        """When a question is rejected for missing subject keyword, the retry
        prompt should tell the model to include the subject name."""
        off_subject = {"question": "What is a stack?"}
        self.model.side_effect = [
            START_Q,  # for _start_java
            off_subject,  # attempt 0: fails subject_matches
            VALID_JAVA_Q,  # attempt 1: passes
        ]
        started = await self._start_java()
        request = self._next_request(started, history_count=2)
        await engine.process_adaptive_next_question(request)
        # The retry call's prompt (3rd overall call) should reference the subject
        retry_call_prompt = self.model.call_args_list[2].kwargs.get("prompt", "")
        self.assertIn("Java", retry_call_prompt)
        self.assertIn("subject", retry_call_prompt.lower())

    # ── Scenario 9: Fallback does NOT bypass category or HR behavior ──
    def test_fallback_strictly_rejects_hr_and_non_technical(self):
        """HR interviews must NEVER receive technical fallback questions."""
        with self.assertRaises(engine.LLMResponseParseError):
            engine.generate_fallback_question(
                decision="NEXT_TOPIC",
                target_skill="Java",
                target_concept="Java basics",
                difficulty="Medium",
                category="HR",
                subject="Java",
            )

    # ── Scenario 10: Fallback enforces subject anchoring ──
    def test_fallback_enforces_subject_anchoring(self):
        """Deterministic fallback questions must include the required subject keyword."""
        q = engine.generate_fallback_question(
            decision="DEEPER_CHALLENGE",
            target_skill="concurrency",
            target_concept="thread pools",
            difficulty="Hard",
            category="Technical",
            subject="Java",
        )
        self.assertIn("Java", q.question)
        self.assertTrue(engine.subject_matches(q.question, "Java"))

    # ── Scenario 11: Fallback enforces duplicate prevention ──
    def test_fallback_enforces_duplicate_checks_against_history(self):
        """If a fallback template already exists in history, fallback must not duplicate it."""
        # Prepopulate history with the primary fallback question
        q1 = engine.generate_fallback_question(
            decision="NEXT_TOPIC",
            target_skill="Java types and variables",
            target_concept="types",
            difficulty="Medium",
            category="Technical",
            subject="Java",
        )
        history = [q1.question]
        # Request a new fallback with history provided
        q2 = engine.generate_fallback_question(
            decision="NEXT_TOPIC",
            target_skill="Java types and variables",
            target_concept="types",
            difficulty="Medium",
            category="Technical",
            subject="Java",
            history=history,
        )
        self.assertNotEqual(q1.question, q2.question)
        self.assertNotIn(q2.question, history)

    # ── Scenario 12: Full 3-question consecutive flow ──
    async def test_three_consecutive_questions_flow(self):
        """End-to-end verification of Questions 1, 2, and 3 in a real sequence."""
        # 1. Start interview (Q1)
        start_res = await self._start_java()
        q1 = start_res.first_question
        self.assertIsNotNone(q1)
        self.assertEqual(q1.category, "Technical")
        self.assertIn("Java", q1.question)

        # 2. Answer Q1 -> Generate Q2
        q2_model_output = {"question": "What is the difference between ArrayList and LinkedList in Java?"}
        self.model.return_value = q2_model_output
        req2 = AdaptiveNextQuestionRequest(
            previous_question=q1.question,
            candidate_answer="The JVM compiles bytecode to machine code.",
            evaluation=evaluation(75),
            interview_plan=start_res.interview_plan,
            interview_state=start_res.interview_state,
            current_topic=q1.topic,
            question_history=[q1.question],
            category="Technical",
        )
        res2 = await engine.process_adaptive_next_question(req2)
        q2 = res2.question
        self.assertIsNotNone(q2)
        self.assertEqual(res2.interview_state["questions_asked"], 2)

        # 3. Answer Q2 -> Generate Q3 (where model first returns off-subject, then valid on retry)
        off_subject = {"question": "What is a binary search tree?"}
        valid_q3 = {"question": "How does garbage collection work in Java?"}
        self.model.side_effect = [off_subject, valid_q3]

        req3 = AdaptiveNextQuestionRequest(
            previous_question=q2.question,
            candidate_answer="ArrayList uses a dynamic array while LinkedList uses pointers.",
            evaluation=evaluation(80),
            interview_plan=res2.interview_plan,
            interview_state=res2.interview_state,
            current_topic=q2.topic,
            question_history=[q1.question, q2.question],
            category="Technical",
        )
        res3 = await engine.process_adaptive_next_question(req3)
        q3 = res3.question
        self.assertIsNotNone(q3)
        self.assertIn("Java", q3.question)
        self.assertEqual(res3.interview_state["questions_asked"], 3)
        self.assertFalse(res3.end_interview)


if __name__ == "__main__":
    unittest.main()
