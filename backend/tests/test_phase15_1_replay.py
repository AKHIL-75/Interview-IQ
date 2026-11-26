"""Commit/retry tests with isolated persistence adapters; no production auth bypass."""
import asyncio
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.core.inference import current_engine
from app.services import interview_commit as commit
from app.api.v1.endpoints import evaluation as endpoint
from app.schemas.adaptive import AdaptiveNextQuestionRequest, AdaptiveNextQuestionResponse
from app.schemas.evaluation import AnswerEvaluationRequest, AnswerEvaluationResponse
from app.schemas.analysis import MatchAnalysisRequest
from pydantic import ValidationError

class ReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_adaptive_turn_uses_engine_from_owned_session_and_restores_scope(self):
        self.session["interview_config"] = {"inference_engine": "aws"}

        async def generate(request):
            self.assertEqual(current_engine(), "aws")
            return self.response

        self.generate.side_effect = generate
        await commit.commit_answer(self.request(), self.auth)
        self.generate.assert_awaited_once()
        self.assertEqual(current_engine(), "local")

    async def test_provider_failure_preserves_session_and_retry_reuses_saved_evaluation(self):
        from app.services.llm_service import LLMResponseParseError
        original = deepcopy(self.session)
        self.generate.side_effect = [LLMResponseParseError('invalid output'), self.response]
        with self.assertRaises(LLMResponseParseError):
            await commit.commit_answer(self.request(), self.auth)
        self.assertEqual(self.session, original)
        self.persist.assert_not_awaited()
        self.update.assert_not_awaited()
        await commit.commit_answer(self.request(), self.auth)
        await commit.commit_answer(self.request(), self.auth)
        self.assertEqual(self.generate.await_count, 2)
        self.persist.assert_awaited_once()

    def setUp(self):
        self.auth=SimpleNamespace(user_id='owner',token='test-token')
        self.session=dict(id='db-session',session_id='session',status='active',interview_type='Technical',interview_state={},interview_plan={})
        self.question=dict(id='db-q1',question_id='q1',question_text='Explain transactions',question_order=1)
        self.answer=dict(question_id='db-q1',answer_text='Atomic units of work',score=70,technical_accuracy=0,relevance=90,depth=80,clarity=90,strengths=['Relevant'],improvements=['Describe rollback'],suggested_answer='Explain ACID')
        self.response=AdaptiveNextQuestionResponse(decision='NEXT_TOPIC',reason='Covered topic',question=dict(id='q2',question='Explain transaction isolation',topic='SQL'),interview_state={'questions_asked':2},interview_plan={})
        self.read=AsyncMock(side_effect=self.rows)
        self.generate=AsyncMock(return_value=self.response)
        self.update=AsyncMock(side_effect=self.save)
        self.persist=AsyncMock(return_value={'id':'db-q2'})
        for name,mock in [('read_owned_rows',self.read),('process_adaptive_next_question',self.generate),('update_interview_session',self.update),('persist_interview_question',self.persist)]:
            patcher=patch.object(commit,name,mock);patcher.start();self.addCleanup(patcher.stop)
    async def rows(self,token,table,filters):
        self.assertEqual(token,'test-token')
        return deepcopy({'interview_sessions':[self.session],'interview_questions':[self.question],'candidate_answers':[self.answer]}[table])
    async def save(self,token,session_id,data):
        self.session.update(deepcopy(data));return self.session
    def request(self,answer='Atomic units of work'):
        return AdaptiveNextQuestionRequest(session_id='session',previous_question='Explain transactions',candidate_answer=answer,evaluation={'score':100},answer_history=[{'questionId':'q1'}],question_history=['forged history'])
    async def test_duplicate_calls_generate_and_persist_once(self):
        a,b=await asyncio.gather(commit.commit_answer(self.request(),self.auth),commit.commit_answer(self.request(),self.auth))
        self.assertEqual(a.question.id,b.question.id);self.generate.assert_awaited_once();self.persist.assert_awaited_once()
        supplied=self.generate.call_args.args[0]
        self.assertEqual(supplied.evaluation.technicalAccuracy,0)
        self.assertEqual(supplied.evaluation.score,70)
        self.assertEqual(supplied.question_history,['Explain transactions'])
        self.assertEqual(self.persist.call_args.kwargs['session_db_uuid'], 'db-session')
        self.assertEqual(commit._locks,{})
    async def test_partial_write_replays_without_regeneration(self):
        self.persist.side_effect=[None,{'id':'db-q2'}]
        with self.assertRaises(HTTPException) as caught: await commit.commit_answer(self.request(),self.auth)
        self.assertEqual(caught.exception.status_code,503)
        self.assertFalse(self.session['interview_state']['_submission']['committed'])
        response=await commit.commit_answer(self.request(),self.auth)
        self.assertEqual(response.question.id,'q2');self.generate.assert_awaited_once()
        self.assertTrue(self.session['interview_state']['_submission']['committed'])
    async def test_changed_answer_rejected_after_commit(self):
        await commit.commit_answer(self.request(),self.auth)
        with self.assertRaises(HTTPException) as caught: await commit.commit_answer(self.request('Changed answer'),self.auth)
        self.assertEqual(caught.exception.status_code,409);self.generate.assert_awaited_once()
    async def test_no_owned_session_rejected(self):
        self.read.side_effect=None;self.read.return_value=[]
        with self.assertRaises(HTTPException) as caught: await commit.commit_answer(self.request(),self.auth)
        self.assertEqual(caught.exception.status_code,404);self.generate.assert_not_awaited()
    async def test_missing_saved_evaluation_never_advances(self):
        self.answer['answer_text']='different saved answer'
        with self.assertRaises(HTTPException) as caught: await commit.commit_answer(self.request(),self.auth)
        self.assertEqual(caught.exception.status_code,409);self.generate.assert_not_awaited()
    async def test_evaluation_replays_saved_feedback_without_model(self):
        with patch.object(endpoint,'read_owned_rows',self.read),patch.object(endpoint,'evaluate_candidate_answer',new_callable=AsyncMock) as model:
            result=await endpoint.evaluate_answer(AnswerEvaluationRequest(session_id='session',question_id='q1',question='Explain transactions',candidate_answer='Atomic units of work'),self.auth)
        self.assertEqual(result.technicalAccuracy,0);self.assertEqual(result.improvements,['Describe rollback']);model.assert_not_awaited()
    async def test_evaluation_save_failure_is_not_success(self):
        async def rows(token,table,filters): return [] if table=='candidate_answers' else await self.rows(token,table,filters)
        result=AnswerEvaluationResponse(score=70,technicalAccuracy=0,relevance=90,depth=80,clarity=90,strengths=[],improvements=[],suggestedAnswer='')
        with patch.object(endpoint,'read_owned_rows',side_effect=rows),patch.object(endpoint,'evaluate_candidate_answer',AsyncMock(return_value=result)),patch.object(endpoint,'persist_candidate_answer',AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as caught:
                await endpoint.evaluate_answer(AnswerEvaluationRequest(session_id='session',question_id='q1',question='Explain transactions',candidate_answer='Atomic units of work'),self.auth)
        self.assertEqual(caught.exception.status_code,503)

class ContractTests(unittest.TestCase):
    def test_shifted_analysis_arguments_rejected(self):
        payload={'candidate_profile':'test-user','job_profile':{'extracted_skills':['Python']},'threshold':{'required_skills':['Python']}}
        response=TestClient(app).post('/api/v1/analysis/match',json=payload)
        self.assertEqual(response.status_code,422)
        self.assertEqual(response.headers['content-type'],'application/problem+json')
        self.assertIsInstance(response.json()['detail'],str)
        self.assertNotIn('test-user',response.text)
        self.assertNotIn('input',response.json())
        # Verify rejection locations internally; submitted values stay out of HTTP errors.
        with self.assertRaises(ValidationError) as caught:
            MatchAnalysisRequest.model_validate(payload)
        self.assertEqual([x['loc'][-1] for x in caught.exception.errors()],['candidate_profile','threshold'])
    def test_cors_exact_local_origin(self):
        client=TestClient(app)
        for origin,allowed in [('http://127.0.0.1:5173',True),('http://untrusted.invalid',False)]:
            response=client.options('/api/v1/health',headers={'Origin':origin,'Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'authorization,content-type'})
            self.assertEqual(response.headers.get('access-control-allow-origin'),origin if allowed else None)

if __name__=='__main__': unittest.main(verbosity=2)

