import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from fastapi import HTTPException
from app.services import adaptive_interviewer as engine, evaluator, llm_service
from app.services.report_generator import generate_final_report
from app.services.question_policy import category_matches
from app.schemas.evaluation import AnswerEvaluationRequest
from app.schemas.adaptive import AdaptiveNextQuestionRequest
from app.api.v1.endpoints import interview

QUESTION = 'Can you share a specific time when you had to resolve a disagreement with a teammate during a project?'
REFERENCE = 'Illustrative example: Situation: Our team disagreed about scope. Task: I needed agreement. Action: I heard both views and proposed a small trial. Result: We agreed on priorities and completed the work.'
EVAL = dict(answer_status='PARTIAL', technicalAccuracy=65, relevance=75, depth=60, clarity=80, strengths=['Clear actions'], improvements=['Explain the result'], suggestedAnswer=REFERENCE)


class SubmissionFixTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_preserves_zero_when_a_legacy_alias_has_a_value(self):
        report = generate_final_report('s', 'Engineer', 'Technical', 'Easy',
            [{'id': 'q1', 'question': 'What is SQL?'}],
            [{'questionId': 'q1', 'answer': "I don't know", 'evaluation': {
                **EVAL, 'score': 0, 'technical_accuracy': 0, 'technicalAccuracy': 80}}])
        self.assertEqual(report['scores']['technical_accuracy'], 0)
        self.assertEqual(report['question_analysis'][0]['technical_accuracy'], 0)

    async def test_reference_schema_is_sent_and_reasoning_is_not_an_answer(self):
        import httpx
        schema = {'type': 'object', 'properties': {'suggestedAnswer': {'type': 'string'}}, 'required': ['suggestedAnswer']}
        client = AsyncMock()
        client.post.return_value = httpx.Response(200, json={'response': '{"suggestedAnswer":"A real reference"}', 'done_reason': 'stop'})
        manager = AsyncMock(); manager.__aenter__.return_value = client
        with patch.object(llm_service.httpx, 'AsyncClient', return_value=manager):
            result = await llm_service.generate_json_response('Synthetic question', response_schema=schema)
            self.assertEqual(client.post.call_args.kwargs['json']['format'], schema)
            self.assertEqual(result['suggestedAnswer'], 'A real reference')
            for envelope in [[], {'response': None}, {'response': '', 'thinking': '{"score":0}'}, {'response': '{"private-answer":'}]:
                client.post.return_value = httpx.Response(200, json=envelope)
                with self.assertRaises(llm_service.LLMResponseParseError) as error:
                    await llm_service.generate_json_response('Synthetic question')
                self.assertNotIn('private-answer', str(error.exception))

    async def test_exact_live_provider_outputs_are_hr(self):
        for text in [
            'Can you describe a specific action you took to improve team communication last week?',
            'Can you share a recent personal action that improved team communication?',
            'Can you describe a specific disagreement you resolved within a team project?',
            'Can you describe a time when you worked with a teammate on a small task without any disagreements?',
            'Tell me about a time you worked with others on a project.',
            'Can you think of a recent time when you had to collaborate with someone on a project and faced a disagreement?',
            'Can you describe a recent time when you worked with a teammate on a project and had a disagreement?']:
            self.assertTrue(category_matches(text, 'HR'))
            with patch.object(engine.llm_service, 'generate_json_response', AsyncMock(return_value={'question':text})), patch.object(engine, 'semantic_duplicate', return_value=False):
                q,_=await engine.generate_single_next_question('RECOVERY_QUESTION','BEHAVIORAL','Teamwork','Teamwork','Easy','HR','Engineer',previous_question=QUESTION)
                self.assertEqual(q.question,text)
        self.assertFalse(category_matches('Describe a time you had a disagreement and explain the database indexing implementation.', 'HR'))

    async def test_internal_error_is_500_not_502(self):
        with patch.object(interview, 'commit_answer', AsyncMock(side_effect=RuntimeError('private input'))):
            with self.assertRaises(HTTPException) as error:
                await interview.next_question(AdaptiveNextQuestionRequest(previous_question=QUESTION,candidate_answer='test'), SimpleNamespace())
        self.assertEqual(error.exception.status_code,500)
        self.assertNotIn('private',error.exception.detail)
        with patch.object(engine.llm_service, 'generate_json_response', AsyncMock(side_effect=RuntimeError('bug'))):
            with self.assertRaises(RuntimeError):
                await engine.generate_single_next_question('NEXT_TOPIC','BEHAVIORAL','Teamwork','Teamwork','Easy','HR','Engineer')

    async def test_echoed_question_and_candidate_are_regenerated(self):
        for echo in [QUESTION, 'I listened and proposed a trial.']:
            request=AnswerEvaluationRequest(question=QUESTION,candidate_answer='I listened and proposed a trial.',category='HR')
            with patch.object(llm_service,'generate_json_response',AsyncMock(side_effect=[{**EVAL,'suggestedAnswer':echo},{'suggestedAnswer':REFERENCE}])) as model:
                result=await evaluator.evaluate_candidate_answer(request)
            self.assertEqual(result.suggestedAnswer,REFERENCE)
            self.assertEqual(model.await_count,2)

    async def test_non_answer_zero_has_real_reference_not_expected_concepts(self):
        request=AnswerEvaluationRequest(question=QUESTION,candidate_answer="I don't know",expected_answer=QUESTION,category='HR')
        with patch.object(llm_service,'generate_json_response',AsyncMock(return_value={'suggestedAnswer':REFERENCE})):
            result=await evaluator.evaluate_candidate_answer(request)
        self.assertEqual(result.score,0)
        self.assertEqual(result.answer_status,'NON_ANSWER')
        self.assertEqual(result.suggestedAnswer,REFERENCE)

    async def test_failed_or_malformed_model_is_not_a_valid_zero(self):
        req=AnswerEvaluationRequest(question=QUESTION,candidate_answer='I listened to each person.',category='HR')
        for output in [[],{}, {**EVAL,'answer_status':'FAILED'}, {**EVAL,'clarity':None}, {**EVAL,'relevance':-10}, {**EVAL,'technicalAccuracy':float('nan')}]:
            with patch.object(llm_service,'generate_json_response',AsyncMock(return_value=output)):
                with self.assertRaises(llm_service.LLMResponseParseError): await evaluator.evaluate_candidate_answer(req)
        with patch.object(llm_service,'generate_json_response',AsyncMock(side_effect=llm_service.OllamaTimeoutError('timeout'))):
            with self.assertRaises(llm_service.OllamaTimeoutError): await evaluator.evaluate_candidate_answer(req)

    async def test_report_joins_by_identity_and_excludes_failed_scores(self):
        questions=[{'id':'q1','question':QUESTION},{'id':'q2','question':'What is a SQL index?'}]
        answers=[{'questionId':'q2','answer':'Index answer','evaluation':{**EVAL,'score':0,'answer_status':'FAILED'}},
                 {'questionId':'q1','answer':"I don't know",'evaluation':{**EVAL,'score':0,'answer_status':'NON_ANSWER','suggestedAnswer':QUESTION}}]
        report=generate_final_report('s','Engineer','HR','Easy',questions,answers)
        rows=report['question_analysis']
        self.assertIsNone(rows[0]['score'])
        self.assertEqual(rows[0]['evaluation_status'],'UNAVAILABLE')
        self.assertEqual(rows[0]['improvements'],[])
        self.assertEqual(rows[1]['score'],0)
        self.assertEqual(rows[1]['question'],QUESTION)
        self.assertEqual(rows[1]['suggested_answer'],'')
        self.assertEqual(report['scores']['questions_evaluated'],1)
