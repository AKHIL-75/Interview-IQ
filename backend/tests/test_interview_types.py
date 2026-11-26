"""Interview-type regression tests. Model and persistence boundaries are controlled."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError
from fastapi import HTTPException
from app.schemas.adaptive import InterviewStartRequest, AdaptiveNextQuestionRequest
from app.schemas.interview import QuestionGenerationRequest
from app.services import adaptive_interviewer as engine, interview_commit as commit
from app.services.question_policy import category_matches, HR_TOPICS
from app.services.question_generator import generate_interview_questions, generate_fallback_question
from app.prompts.evaluation_prompts import detect_question_type
from app.services.report_generator import generate_final_report, normalize_report_for_response

HR = 'How did you resolve a disagreement with a teammate on your Java project?'
TECH = 'Explain the difference between HashMap and ConcurrentHashMap in Java.'

def evaluation(score):
    return dict(score=score, technicalAccuracy=score, relevance=score, depth=score, clarity=score,
                answer_status='INCORRECT' if score < 40 else 'CORRECT')

class IntentTests(unittest.TestCase):
    def test_behavioral_intent_accepts_technical_context(self):
        for question in [HR, 'Tell me about a time you handled a difficult situation.',
                'How do you resolve disagreements within a team?', 'What motivates you to apply for this role?',
                'Describe a mistake you made and what you learned.', 'How do you prioritize competing deadlines?',
                'What are your strengths and what skill are you working to improve?',
                'Describe a situation where you received constructive feedback.', 'Why do you want to join this company?',
                'How would you explain database indexing to a non-technical stakeholder?',
                'Describe how you handled a disagreement over Java architecture.']:
            with self.subTest(question=question): self.assertTrue(category_matches(question, 'HR'))

    def test_hr_rejects_technical_assessment_even_with_behavioral_label_or_words(self):
        for question in [TECH, 'What is polymorphism in Java?', 'Write a program to reverse a linked list.',
                'Explain database normalization.', 'What is the difference between TCP and UDP?',
                'Explain operating-system scheduling algorithms.',
                "Describe how your team implemented the project's database indexing.",
                'Tell me how you handled a disagreement and explain the database indexing implementation.',
                'Explain polymorphism and explain your decision to a non-technical stakeholder.',
                'What is a frobnicator?', 'Tell me about your educational background.']:
            with self.subTest(question=question): self.assertFalse(category_matches(question, 'HR'))
        self.assertFalse(category_matches(HR, 'Technical'))
        self.assertTrue(category_matches(TECH, 'Technical'))

    def test_hr_project_uses_behavioral_rubric(self):
        self.assertEqual(detect_question_type(HR, 'PROJECT', 'HR', 'Candidate project'), 'HR_BEHAVIORAL')
        self.assertEqual(detect_question_type(TECH, category='Technical'), 'TECHNICAL')

    def test_invalid_request_type_and_subject_rejected_default_preserved(self):
        self.assertEqual(InterviewStartRequest().interview_type, 'Technical')  # Existing API default.
        for payload in [{'interview_type': None}, {'interview_type': 'Behavioral'}, {'interview_type':'HR','subject':'Java'}]:
            with self.subTest(payload=payload), self.assertRaises(ValidationError): InterviewStartRequest(**payload)

class GenerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.model = AsyncMock(return_value={'question': HR})
        for name, value in [('generate_json_response', self.model)]:
            p = patch.object(engine.llm_service, name, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(engine, 'semantic_duplicate', return_value=False); p.start(); self.addCleanup(p.stop)

    async def start(self, kind='HR', count=5):
        return await engine.process_adaptive_start(InterviewStartRequest(interview_type=kind, question_count=count,
            candidate_profile={'skills':['Java','SQL'], 'projects':[{'name':'Order service'}]}))

    def request(self, started, score=60):
        return AdaptiveNextQuestionRequest(previous_question=started.first_question.question, candidate_answer='My example',
            evaluation=evaluation(score), category=started.first_question.category,
            question_history=[started.first_question.question], interview_plan=started.interview_plan,
            interview_state=started.interview_state, current_topic=started.first_question.topic)

    async def test_hr_start_plan_and_persistence(self):
        from app.api.v1.endpoints import interview
        with patch.object(interview, 'persist_interview_session', AsyncMock(return_value={'id':'s'})) as save, patch.object(interview, 'persist_interview_question', AsyncMock(return_value={'id':'q'})):
            result = await interview.start_interview(InterviewStartRequest(interview_type='HR'), SimpleNamespace(user_id='owner', token='token'))
        self.assertEqual(result.first_question.category, 'HR')
        self.assertEqual(result.first_question.stage, 'INTRO')
        self.assertEqual(result.interview_plan['skills_priority'], HR_TOPICS)
        self.assertEqual(save.call_args.kwargs['interview_type'], 'HR')
        self.assertEqual(save.call_args.kwargs['interview_config']['interview_type'], 'HR')
        self.assertEqual(result.interview_state['interview_type'], 'HR')
        self.assertEqual(result.interview_plan['stages_planned'].count('INTRO'), 1)
        self.model.assert_not_awaited()

    async def test_hr_first_generated_question_rejects_technical_then_retries(self):
        started = await self.start()
        self.model.side_effect = [{'question':TECH, 'category':'HR'}, {'question':HR}]
        result = await engine.process_adaptive_next_question(self.request(started))
        self.assertEqual(result.question.question, HR)
        self.assertEqual(result.question.category, 'HR')
        self.assertEqual(result.question.stage, 'ADAPTIVE')
        self.assertEqual(self.model.await_count, 2)
        for call in self.model.call_args_list:
            self.assertIn('REQUIRED QUESTION CATEGORY: HR', call.kwargs['prompt'])
            self.assertNotIn('human technical interviewer', call.kwargs['prompt'])
            self.assertNotIn('core mechanics and design principles', call.kwargs['prompt'])

    async def test_failed_hr_output_advances_using_validated_fallback(self):
        request = self.request(await self.start())
        before = copy.deepcopy(request.model_dump())
        self.model.return_value = {'question':TECH}
        result = await engine.process_adaptive_next_question(request)
        self.assertEqual(result.question.id, 'q2')
        self.assertEqual(result.question.category, 'HR')
        self.assertTrue(category_matches(result.question.question, 'HR'))
        self.assertFalse(engine.is_duplicate_question(result.question.question, request.question_history))
        self.assertEqual(result.interview_state['questions_asked'], 2)
        self.assertEqual(request.model_dump(), before)
        self.assertEqual(self.model.await_count, engine.MAX_GENERATION_RETRIES + 1)

    async def test_hr_strong_weak_and_partial_followups_keep_behavioral_scope(self):
        for score in [10,60,95]:
            with self.subTest(score=score):
                started = await self.start()
                req = self.request(started, score)
                req.previous_question = 'How do you prioritize competing deadlines?'
                req.question_history = [started.first_question.question, req.previous_question]
                req.interview_state.update(current_stage='BEHAVIORAL', current_topic=HR_TOPICS[2], questions_asked=2,
                    category_counts={'HR':2,'Technical':0})
                req.current_topic = HR_TOPICS[2]
                req.category = 'Technical'  # A stale question label cannot override the saved HR plan.
                result = await engine.process_adaptive_next_question(req)
                self.assertEqual(result.question.category, 'HR')
                self.assertTrue(category_matches(result.question.question, 'HR'))
                self.assertEqual(result.interview_state['interview_type'], 'HR')
                self.assertNotEqual(result.question.stage, 'INTRO')
                self.assertEqual(result.question.difficulty, 'Easy' if score == 10 else 'Medium')

    async def test_mixed_budget_including_recovery_followups(self):
        for count in [2,5,6,10]:
            with self.subTest(count=count):
                started = await self.start('Mixed', count)
                req = self.request(started, 10)
                categories = [started.first_question.category]
                async def generated(**kwargs):
                    category = 'HR' if 'REQUIRED QUESTION CATEGORY: HR' in kwargs['prompt'] else 'Technical'
                    return {'question': f'How do you resolve disagreements within a team in situation {len(categories)}?' if category == 'HR'
                            else f'Explain Java interface contract number {len(categories)}.'}
                self.model.side_effect = generated
                with patch.object(engine, 'is_duplicate_question', return_value=False):
                    for _ in range(count - 1):
                        result = await engine.process_adaptive_next_question(req)
                        categories.append(result.question.category)
                        req.interview_plan = result.interview_plan
                        req.interview_state = result.interview_state
                        req.previous_question = result.question.question
                        req.question_history.append(result.question.question)
                        req.category = result.question.category
                        req.current_topic = result.question.topic
                        req.consecutive_follow_ups = result.interview_state['consecutive_follow_ups']
                    ended = await engine.process_adaptive_next_question(req)
                self.assertTrue(ended.end_interview)
                self.assertLessEqual(abs(categories.count('HR') - categories.count('Technical')), 1)
                self.assertIn('HR', categories); self.assertIn('Technical', categories)
                self.assertEqual(req.interview_plan['category_schedule'], started.interview_plan['category_schedule'])

    async def test_missing_or_invalid_saved_type_fails_before_model(self):
        req = self.request(await self.start())
        for plan in [{}, {'interview_type':'invalid'}, {'interview_type':'HR','subject':'Java'}]:
            req.interview_plan = plan
            with self.assertRaises(engine.InterviewStateError): await engine.process_adaptive_next_question(req)
        self.model.assert_not_awaited()

    async def test_legacy_hr_and_mixed_bulk_use_same_validation(self):
        self.model.side_effect = [{'question':TECH}, {'question':HR}]
        result = await generate_interview_questions(QuestionGenerationRequest(candidate_profile={}, job_profile={}, interview_type='HR', question_count=2))
        self.assertEqual([q.category for q in result.questions], ['HR','HR'])
        self.model.side_effect = [{'question':TECH}, {'question':HR}]
        mixed = await generate_interview_questions(QuestionGenerationRequest(candidate_profile={}, job_profile={}, interview_type='Mixed', question_count=3))
        self.assertEqual([q.category for q in mixed.questions], ['HR','Technical','HR'])
        self.model.side_effect = None; self.model.return_value = {'question':TECH}
        recovered = await generate_interview_questions(QuestionGenerationRequest(
            candidate_profile={}, job_profile={}, interview_type='HR', question_count=2))
        self.assertEqual(recovered.count, 2)
        self.assertTrue(category_matches(recovered.questions[1].question, 'HR'))
        self.assertNotEqual(recovered.questions[1].question, TECH)

    async def test_hr_retry_exhaustion_keeps_follow_up_with_the_project_and_team(self):
        previous = 'How did you resolve a disagreement with a teammate on Catalog Search?'
        answer = 'We disagreed about the implementation, so I discussed the options with the team.'
        self.model.side_effect = [{'question': TECH},
            {'question': 'What motivates you to pursue this role?'}, {'question': previous},
            engine.LLMResponseParseError('malformed')]
        q, _ = await engine.generate_single_next_question(
            decision='TARGETED_FOLLOW_UP', stage='BEHAVIORAL', target_skill=HR_TOPICS[0],
            target_concept=HR_TOPICS[0], difficulty='Medium', category='HR', role='Engineer',
            previous_question=previous, candidate_answer=answer, project_name='Catalog Search')
        self.assertEqual(self.model.await_count, engine.MAX_GENERATION_RETRIES + 1)
        self.assertIn('Catalog Search', q.question)
        self.assertIn('best for the team', q.question)
        self.assertTrue(q.is_follow_up)
        self.assertTrue(category_matches(q.question, 'HR'))

    async def test_hr_next_topic_names_project_only_when_the_question_refers_to_it(self):
        q_text = 'Can you describe a disagreement you handled during that project?'
        plain = 'What motivates you to pursue this role?'
        self.model.side_effect = [{'question': q_text}, {'question': plain}]
        for expected in ('For your Catalog Search project, ' + q_text[0].lower() + q_text[1:], plain):
            q, _ = await engine.generate_single_next_question(
                decision='NEXT_TOPIC', stage='BEHAVIORAL', target_skill=HR_TOPICS[0],
                target_concept=HR_TOPICS[0], difficulty='Medium', category='HR', role='Engineer',
                previous_question='Could you introduce yourself?', candidate_answer='I worked on Catalog Search.',
                project_name='Catalog Search')
            self.assertEqual(q.question, expected)

    async def test_hr_turns_continue_from_serialized_state_after_malformed_output(self):
        import json
        self.model.side_effect = engine.LLMResponseParseError('malformed')
        for count in (5, 10, 20):
            started = await self.start('HR', count)
            req = self.request(started, 10)
            for _ in range(count - 1):
                result = await engine.process_adaptive_next_question(req)
                q = result.question
                self.assertTrue(category_matches(q.question, 'HR'))
                self.assertFalse(engine.is_duplicate_question(q.question, req.question_history))
                if result.decision == 'NEXT_TOPIC':
                    self.assertFalse(q.is_follow_up)
                req = AdaptiveNextQuestionRequest.model_validate_json(json.dumps({
                    **req.model_dump(), 'interview_plan':result.interview_plan,
                    'interview_state':result.interview_state, 'previous_question':q.question,
                    'current_topic':q.topic, 'category':q.category, 'candidate_answer':'I do not know.',
                    'question_history':[*req.question_history, q.question],
                    'consecutive_follow_ups':result.interview_state['consecutive_follow_ups'],
                }))
            self.assertTrue((await engine.process_adaptive_next_question(req)).end_interview)
            self.assertEqual(len(req.question_history), count)

    async def test_general_technical_and_subjects_still_reject_hr(self):
        for subject in [None,'Java','OOP']:
            good = TECH if subject != 'OOP' else 'What is encapsulation in object-oriented programming?'
            self.model.side_effect = [{'question':HR}, {'question':good}]
            if subject:
                result = await engine.process_adaptive_start(InterviewStartRequest(subject=subject))
                question = result.first_question
            else:
                result = await engine.process_adaptive_next_question(self.request(await self.start('Technical')))
                question = result.question
            self.assertEqual(question.category, 'Technical')
            self.assertEqual(question.question, good)

    async def test_legacy_hr_followup_validator_and_fallback_guard(self):
        self.model.side_effect = [{'question':TECH}, {'question':HR}]
        decision = engine.AdaptiveDecisionResult(decision='TARGETED_FOLLOW_UP',reason='gap',target_skill='Teamwork',
            target_concept='Resolving disagreement',difficulty='Medium',next_difficulty='Medium',is_follow_up=True)
        result = await engine.execute_adaptive_generation(decision, 'How do you prioritize deadlines?', 'An example',
            engine.AdaptiveEvaluationInput(**evaluation(60)), 'HR', 'Engineer', [])
        self.assertEqual(result.question, HR)
        with self.assertRaises(engine.LLMResponseParseError): engine.generate_fallback_question('NEXT_TOPIC','Java','Java','Medium','HR')

    def test_hr_report_survives_history_normalization(self):
        report = generate_final_report('s','Engineer','HR','Medium',[],[],interview_plan={'interview_type':'HR'})
        self.assertEqual(normalize_report_for_response(report)['interview_type'], 'HR')

