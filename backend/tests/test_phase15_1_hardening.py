import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app
from app.services.evaluator import _extract_dimension_scores, evaluate_candidate_answer
from app.services.llm_service import LLMResponseParseError
from app.services.report_generator import generate_final_report, normalize_report_for_response
from app.services.adaptive_interviewer import decide_next_action
from app.schemas.adaptive import AdaptiveEvaluationInput
from app.schemas.evaluation import AnswerEvaluationRequest

class HardeningTests(unittest.TestCase):
    def test_dimensions_preserve_zero_and_requested_values(self):
        for n in [0,10,25,50,75,100]:
            with self.subTest(score=n):
                self.assertEqual(_extract_dimension_scores(dict(technicalAccuracy=n,relevance=n,depth=n,clarity=n)),(n,n,n,n))
    def test_alias_zero_wins_over_fallback(self):
        self.assertEqual(_extract_dimension_scores(dict(technicalAccuracy=0,technical_accuracy=80,relevance=0,depth=0,clarity=0)),(0,0,0,0))
    def test_missing_dimensions_raise(self):
        with self.assertRaises(LLMResponseParseError): _extract_dimension_scores({})
    def test_malformed_dimensions_raise(self):
        with self.assertRaises(LLMResponseParseError): _extract_dimension_scores(dict(technicalAccuracy=True,relevance=80,depth=80,clarity=80))
    def test_report_legacy_feedback_and_zero(self):
        result=generate_final_report(session_id='test',role='Engineer',interview_type='Technical',difficulty='Medium',
            questions=[dict(id='q1',question='Explain SQL',topic='SQL')],
            answers=[dict(questionId='q1',answer='Test answer',evaluation=dict(score=40,technicalAccuracy=0,relevance=80,depth=50,clarity=50),feedback=dict(strengths=['Clear terminology'],improvements=['Explain durability'],suggestedAnswer='Use a durable transaction'))])
        report=normalize_report_for_response(result)
        self.assertEqual(report['dimensions']['technical_accuracy'],0)
        q=report['question_analysis'][0]
        self.assertEqual(q['strengths'],['Clear terminology'])
        self.assertEqual(q['improvements'],['Explain durability'])
        self.assertEqual(q['suggested_answer'],'Use a durable transaction')
    def test_no_fabricated_feedback_for_empty_report(self):
        report=generate_final_report(session_id='empty',role='Engineer',interview_type='Technical',difficulty='Medium',questions=[],answers=[])
        self.assertEqual(report['strengths'],[])
        self.assertEqual(report['skill_gaps'],[])
    def test_write_endpoints_require_auth(self):
        client=TestClient(app)
        for path in ['/interview/start','/interview/next-question','/interview/report']:
            with self.subTest(path=path): self.assertEqual(client.post('/api/v1'+path,json={}).status_code,401)
    def test_strong_answer_progresses(self):
        result=decide_next_action(AdaptiveEvaluationInput(score=90,technicalAccuracy=90,relevance=90,depth=90,clarity=90),'Explain SQL',current_topic='SQL',candidate_answer='Detailed explanation')
        self.assertIn(result.decision,['DEEPER_CHALLENGE','ADVANCE_DIFFICULTY','NEXT_TOPIC'])
    def test_weak_answer_follows_up(self):
        result=decide_next_action(AdaptiveEvaluationInput(score=40,technicalAccuracy=30,relevance=85,depth=40,clarity=70),'Explain SQL',current_topic='SQL',candidate_answer='Incomplete explanation')
        self.assertEqual(result.decision,'TARGETED_FOLLOW_UP')

class NonAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_dont_know_has_zero_scores_and_a_reference_answer(self):
        reference = "Isolation controls what concurrent transactions can observe."
        request = AnswerEvaluationRequest(
            question="Explain transaction isolation", candidate_answer="I don't know"
        )
        with patch(
            "app.services.llm_service.generate_json_response",
            new_callable=AsyncMock,
            return_value={"suggestedAnswer": reference},
        ) as generate:
            result = await evaluate_candidate_answer(request)
        generate.assert_awaited_once()
        self.assertIn(request.question, generate.await_args.kwargs["prompt"])
        self.assertEqual(result.answer_status, "NON_ANSWER")
        self.assertEqual(result.suggestedAnswer, reference)
        self.assertEqual(
            (result.score, result.technicalAccuracy, result.relevance, result.depth, result.clarity),
            (0, 0, 0, 0, 0),
        )

if __name__=='__main__': unittest.main(verbosity=2)
