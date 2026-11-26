"""Known-owned records remove lookups, never authentication or durable writes."""
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
import httpx
from app.services import persistence_service as db
from app.api.v1.endpoints import evaluation as endpoint
from app.schemas.evaluation import AnswerEvaluationRequest, AnswerEvaluationResponse


class PersistencePerformanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_owned_records_skip_three_reads_keep_write_and_user_headers(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(201, json=[{"id": "saved"}])
        real_client = httpx.AsyncClient
        def client(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)
        with patch.object(db.settings, 'SUPABASE_URL', 'https://database.invalid'), patch.object(db.settings, 'SUPABASE_ANON_KEY', 'public-key'), \
             patch.object(db.httpx, 'AsyncClient', side_effect=client), \
             patch.object(db, 'get_session_db_uuid', AsyncMock()) as session, \
             patch.object(db, 'get_question_db_uuid', AsyncMock()) as question, \
             patch.object(db, 'read_owned_rows', AsyncMock()) as answers:
            for token in ('user-one', 'user-two'):
                result = await db.persist_candidate_answer(token, 'session', 'q1', 'answer', False, False, 0, {'score': 0},
                    session_db_uuid=token+'-session', question_db_uuid=token+'-question', existing_answers=[])
                self.assertEqual(result, {'id': 'saved'})
            session.assert_not_awaited(); question.assert_not_awaited(); answers.assert_not_awaited()
        self.assertEqual([r.method for r in requests], ['POST', 'POST'])
        self.assertEqual([r.headers['authorization'] for r in requests], ['Bearer user-one', 'Bearer user-two'])
        self.assertTrue(all(r.headers['apikey'] == 'public-key' for r in requests))
        import json
        payloads = [json.loads(r.content) for r in requests]
        self.assertNotEqual(payloads[0]['id'], payloads[1]['id'])
        self.assertEqual(payloads[0]['score'], 0)

    async def test_legacy_caller_resolves_rows_and_reuses_existing_answer_id(self):
        client = AsyncMock()
        client.post.return_value = httpx.Response(201, json=[{'id': 'legacy-answer'}])
        manager = AsyncMock(); manager.__aenter__.return_value = client
        with patch.object(db.settings, 'SUPABASE_URL', 'https://database.invalid'), \
             patch.object(db.httpx, 'AsyncClient', return_value=manager), \
             patch.object(db, 'get_session_db_uuid', AsyncMock(return_value='session-uuid')) as session, \
             patch.object(db, 'get_question_db_uuid', AsyncMock(return_value='question-uuid')) as question, \
             patch.object(db, 'read_owned_rows', AsyncMock(return_value=[{'id': 'legacy-answer'}])) as answers:
            await db.persist_candidate_answer('owner', 'session', 'q1', 'answer', False, False, 0, {'score': 50})
            session.assert_awaited_once(); question.assert_awaited_once(); answers.assert_awaited_once()
            self.assertEqual(client.post.call_args.kwargs['json']['id'], 'legacy-answer')

    async def test_evaluator_passes_only_server_resolved_owned_records(self):
        async def rows(token, table, filters):
            return {'interview_sessions': [{'id': 'owned-session', 'status': 'active'}],
                    'interview_questions': [{'id': 'owned-question', 'question_id': 'q1', 'question_text': 'Explain SQL indexes', 'question_order': 1}],
                    'candidate_answers': []}[table]
        result = AnswerEvaluationResponse(score=70, technicalAccuracy=70, relevance=70, depth=70, clarity=70, strengths=[], improvements=[], suggestedAnswer='')
        with patch.object(endpoint, 'read_owned_rows', side_effect=rows), \
             patch.object(endpoint, 'evaluate_candidate_answer', AsyncMock(return_value=result)), \
             patch.object(endpoint, 'persist_candidate_answer', AsyncMock(return_value={'id':'saved'})) as save:
            await endpoint.evaluate_answer(AnswerEvaluationRequest(session_id='client-session', question_id='q1', question='Explain SQL indexes', candidate_answer='Sorted keys'), SimpleNamespace(user_id='owner', token='owner-token'))
        self.assertEqual(save.call_args.kwargs, {'question_order': 1, 'session_db_uuid': 'owned-session', 'question_db_uuid': 'owned-question', 'existing_answers': []})
        self.assertEqual(save.call_args.args[0], 'owner-token')
