"""Policy/contract regressions. Mock scores test arithmetic, not Qwen judgment."""
import asyncio
import json
from pathlib import Path
import pytest
from app.prompts.evaluation_prompts import build_evaluation_prompt
from app.schemas.evaluation import AnswerEvaluationRequest
from app.services import evaluator
from app.services.report_generator import aggregate_scores, calculate_grade, normalize_report_for_response

CASES = json.loads(Path(__file__).with_name('fixtures').joinpath('evaluation_calibration.json').read_text())
# Synthetic judgments for each distinct evidence profile; these are NOT model quality measurements.
JUDGMENTS = [
    ('CORRECT', (88, 95, 85, 88)), ('PARTIAL', (85, 90, 55, 85)),
    ('PARTIAL', (55, 65, 30, 25)), ('PARTIAL', (60, 75, 40, 35)),
    ('NON_ANSWER', (0, 0, 0, 0)), ('PARTIAL', (95, 95, 85, 95)),
    ('INCORRECT', (10, 90, 15, 95)), ('CORRECT', (95, 95, 90, 90)),
    ('CORRECT', (90, 95, 90, 90)),
]


@pytest.mark.parametrize('case,judgment', list(zip(CASES, JUDGMENTS)), ids=[c['id'] for c in CASES])
def test_evidence_dimensions_and_score_are_not_keyword_overridden(monkeypatch, case, judgment):
    status, dimensions = judgment
    req = AnswerEvaluationRequest(**{k:v for k,v in case.items() if k != 'id'})
    async def model(prompt, **kwargs):
        assert req.candidate_answer in prompt
        if 'Potential false claim to check' in prompt:
            return dict(verdict='FUNDAMENTAL', quote=req.candidate_answer,
                        note='The search mechanism is wrong.', central_impact='It defeats the requested algorithm.', accuracy=10)
        assert 'skills or work experience are optional unless asked' in prompt if case['id'] == 'fresher' else True
        assert 'References are illustrative, not mandatory templates' in prompt
        assert 'Depth has zero weight and no effect on any score or status' in prompt
        return dict(zip(('technicalAccuracy', 'relevance', 'depth', 'clarity'), dimensions),
                    answer_status=status, suggestedAnswer='Illustrative example: A separate sample response.',
                    strengths=['Evidence present'] if status != 'NON_ANSWER' else [], improvements=[])
    monkeypatch.setattr(evaluator.llm_service, 'generate_json_response', model)
    result = asyncio.run(evaluator.evaluate_candidate_answer(req))
    assert tuple(getattr(result,k) for k in ('technicalAccuracy','relevance','depth','clarity')) == dimensions
    accuracy, relevance, _, clarity = dimensions
    expected = round((60 * accuracy + 30 * relevance + 10 * clarity) / 100)
    if status == 'INCORRECT': expected = min(expected,19)
    assert result.score == expected
    assert result.answer_status == status
    if case['id'] == 'irrelevant': assert result.score == 0
    if case['id'] == 'minor_omission': assert result.score >= 80
    if case['id'] == 'fundamental_error': assert result.score <= 19


def test_no_floor_or_introduction_keyword_boost(monkeypatch):
    assert evaluator.calculate_deterministic_score(0, 1, 0, 0, 'PARTIAL') == 0
    async def model(**kwargs):
        return dict(technicalAccuracy=20, relevance=60, depth=10, clarity=15,
                    answer_status='PARTIAL', suggestedAnswer='Illustrative example: State your actual background.')
    monkeypatch.setattr(evaluator.llm_service, 'generate_json_response', model)
    req = AnswerEvaluationRequest(question='Introduce yourself and your background.',
        candidate_answer='My name is Mira. I am a graduate. Java REST API software project college.', stage='INTRO')
    result = asyncio.run(evaluator.evaluate_candidate_answer(req))
    assert (result.technicalAccuracy,result.relevance,result.depth,result.clarity) == (20,60,10,15)
    assert result.answer_status == 'PARTIAL'
    assert result.score == 32


@pytest.mark.parametrize('score,grade', [(0,'F'),(49,'F'),(50,'D'),(59,'D'),(60,'C'),(69,'C'),(70,'B'),(79,'B'),(80,'A'),(89,'A'),(90,'A+'),(100,'A+')])
def test_grade_contract(score,grade):
    assert calculate_grade(score)[0] == grade


def test_followups_have_one_vote_each_and_saved_grade_is_not_rewritten():
    scores = [86,74,48,38,0]
    answers = [dict(score=s,is_follow_up=i>2, evaluation=dict(score=s,technicalAccuracy=s,relevance=s,depth=s,clarity=s)) for i,s in enumerate(scores)]
    result = aggregate_scores(answers, total_planned_questions=20)
    assert result['overall'] == 49 and result['grade'] == 'F'
    assert result['questions_evaluated'] == 5
    assert result['technical_accuracy'] == 49
    assert aggregate_scores([{**a,'is_follow_up':False} for a in answers]) == result
    saved = dict(overall_score=49, scores=dict(grade='F'), question_analysis=[])
    assert normalize_report_for_response(saved)['overall_score'] == 49
    assert normalize_report_for_response(saved)['grade'] == 'F'
    assert saved == dict(overall_score=49,scores=dict(grade='F'),question_analysis=[])


def test_prompt_calibration_has_no_minor_omission_band_or_mandatory_star():
    prompt = build_evaluation_prompt(AnswerEvaluationRequest(question='Explain polymorphism.',candidate_answer='A subtype can implement the same interface differently.'))
    assert '(45-65)' not in prompt
    assert 'Status PARTIAL is not a numeric band or ceiling' in prompt
    assert 'Do not infer success, ownership, causality' in prompt
    assert '90-100 excellent' in prompt
