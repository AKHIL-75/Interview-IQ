"""Boundary checks. The real-model benchmark uses the same predeclared fixture ranges."""
import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.evaluation import AnswerEvaluationRequest
from app.services import evaluator
from app.services.report_generator import generate_final_report


CASES = json.loads(Path(__file__).with_name("fixtures").joinpath("phase20_evaluation.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_calibration_case_uses_candidate_text_and_nonanswer_gate(case):
    if case["id"] == "empty":
        assert evaluator.is_explicit_non_answer(case["request"]["candidate_answer"])
        with pytest.raises(ValidationError):
            AnswerEvaluationRequest(**case["request"])
        return
    req = AnswerEvaluationRequest(**case["request"])
    assert evaluator.is_explicit_non_answer(req.candidate_answer) == (case["id"] == "no_answer")
    assert req.candidate_answer in evaluator.build_evaluation_prompt(req)


@pytest.mark.parametrize("text", [
    "I'm not sure, Java reclaims unreachable objects.",
    "I don’t know the collector, but unreachable objects are reclaimed.",
    "No idea which one; heap objects are collected.",
    "Um, not sure, but sorted inputs are required.",
])
def test_hedging_followed_by_intelligible_evidence_is_scoreable(text):
    assert not evaluator.is_explicit_non_answer(text)


@pytest.mark.parametrize("text", ["Um, I’m not sure.", "I do not know this topic at all.", "Uh.", "Sorry, no clue."])
def test_spoken_non_answers_remain_zero_candidates(text):
    assert evaluator.is_explicit_non_answer(text)


def test_concise_answer_and_report_use_the_same_evidence_scores_and_feedback(monkeypatch):
    calls = []
    async def model(prompt, **kwargs):
        calls.append(kwargs)
        return dict(technicalAccuracy=87, relevance=94, depth=55, clarity=93, answer_status="CORRECT",
                    strengths=["You linked garbage collection to reachability."],
                    improvements=["Explain what the JVM starts from when it checks reachability."],
                    missing_aspects=["Roots for reachability"],
                    suggestedAnswer="Objects are allocated on the heap. Collection finds unreachable objects by tracing from roots.")
    monkeypatch.setattr(evaluator.llm_service, "generate_json_response", model)
    case = next(case for case in CASES if case["id"] == "java_concise")
    req = AnswerEvaluationRequest(**case["request"])
    evaluation = asyncio.run(evaluator.evaluate_candidate_answer(req))
    report = generate_final_report("test", "Engineer", "Technical", "Medium",
        [{"id": "q1", "question": req.question}],
        [{"questionId": "q1", "answer": req.candidate_answer, "evaluation": evaluation.model_dump()}])
    row = report["question_analysis"][0]
    assert evaluation.score == 90
    assert evaluation.missing_aspects == []
    assert row["score"] == report["overall_score"] == evaluation.score
    assert row["strengths"] == evaluation.strengths
    assert row["improvements"] == evaluation.improvements
    assert row["suggested_answer"] == evaluation.suggestedAnswer
    assert not report["skill_gaps"]
    assert len(calls) == 1


def test_relevance_and_central_misconception_gates_cannot_be_evaded_by_clarity():
    score = evaluator.calculate_deterministic_score
    assert score(10, 100, 15, 100, "INCORRECT", dominant_error=True) <= 19
    assert score(10, 20, 15, 100, "INCORRECT", dominant_error=True) <= 10
    assert score(10, 100, 15, 100, "INCORRECT") == 46
    assert score(15, 45, 5, 55, "PARTIAL") <= 39
    assert score(88, 95, 50, 93, "CORRECT") > score(30, 90, 10, 95, "PARTIAL")


@pytest.mark.parametrize(("case_id", "claim", "wanted"), [
    ("java_keywords", None, "PARTIAL"),
    ("dsa_wrong", "checks every item in unsorted data once", "INCORRECT"),
    ("dsa_partial", "scans the entire array", "PARTIAL"),
])
def test_declared_lack_of_evidence_and_misconception_use_only_grounded_claims(
        monkeypatch, case_id, claim, wanted):
    case = next(case for case in CASES if case["id"] == case_id)
    req = AnswerEvaluationRequest(**case["request"])

    async def model(**kwargs):
        if "Potential false claim to check" in kwargs["prompt"]:
            return {"verdict": "FUNDAMENTAL", "quote": claim,
                    "note": "Binary search requires a sorted range and discards half per step.",
                    "central_impact": "Scanning each item contradicts the halving mechanism.", "accuracy": 0}
        return {
            "technicalAccuracy": 66, "relevance": 84, "depth": 55, "clarity": 82,
            "answer_status": "PARTIAL", "evidence": [req.candidate_answer] if claim else [],
            "central_error": {"claim": claim, "reason": "Contradicts the normal search mechanism."} if claim else None,
            "suggestedAnswer": "A different illustrative technical answer.",
        }

    monkeypatch.setattr(evaluator.llm_service, "generate_json_response", model)
    evaluation = asyncio.run(evaluator.evaluate_candidate_answer(req))
    assert evaluation.answer_status == wanted
    if not claim:
        assert evaluation.score <= 39 and evaluation.technicalAccuracy <= 25
    elif wanted == "INCORRECT":
        assert evaluation.score <= 19 and evaluation.technicalAccuracy <= 25
    else:
        assert evaluation.technicalAccuracy == 66


@pytest.mark.parametrize("question_type", ["TECHNICAL", "SYSTEM_DESIGN", "HR_BEHAVIORAL", "INTRODUCTION", "PROJECT", "MIXED"])
def test_scoring_is_invariant_to_depth_and_question_type(question_type):
    for depth in (0, 33, 100):
        assert evaluator.calculate_deterministic_score(94, 96, depth, 90, "CORRECT", question_type) == 94


def test_optional_detail_and_invalid_diagnostic_depth_do_not_change_conceptual_evaluation(monkeypatch):
    from app.services.adaptive_interviewer import decide_next_action
    from app.services.question_policy import performance_level
    from app.schemas.adaptive import AdaptiveEvaluationInput

    outputs = iter([0, 100, "not rated"])

    async def model(prompt, **kwargs):
        assert "optional unless the question asks for them" in prompt
        return dict(technicalAccuracy=95, relevance=100, depth=next(outputs), clarity=95,
                    answer_status="CORRECT", evidence=["Explains the required mechanism"],
                    missing_aspects=["An optional worked example"], improvements=["Optional: Include an example."],
                    suggestedAnswer="A separate sample answer that explains the mechanism.")

    monkeypatch.setattr(evaluator.llm_service, "generate_json_response", model)
    request = AnswerEvaluationRequest(question="How does Java manage memory?",
        candidate_answer="Java frees unreachable objects from the heap automatically.")
    for _ in range(3):
        result = asyncio.run(evaluator.evaluate_candidate_answer(request))
        assert (result.score, result.technicalAccuracy, result.relevance, result.answer_status) == (96, 95, 100, "CORRECT")
        assert result.missing_aspects == []
        adaptive = AdaptiveEvaluationInput.model_validate(result.model_dump())
        assert performance_level(adaptive) == "strong"
        assert decide_next_action(adaptive, "How does Java manage memory?", difficulty="Easy").decision == "ADVANCE_DIFFICULTY"


@pytest.mark.parametrize(("verdict", "quote", "expected_status", "expected_score"), [
    ("MAIN_GAP", "Explain how binary search works", "PARTIAL", 63),
    ("MAIN_GAP", "O(log n) time", "PARTIAL", 63),
    ("TERMS_ONLY", "", "PARTIAL", 39),
    ("MAIN_GAP", "Provide pseudocode", "CORRECT", 93),
])
def test_only_a_requested_main_gap_or_terms_only_can_override_a_high_model_grade(
        monkeypatch, verdict, quote, expected_status, expected_score):
    from unittest.mock import AsyncMock

    first_pass = dict(evidence=["It takes O(log n) time."], central_error=None,
                      answer_status="CORRECT", technicalAccuracy=95, relevance=90, clarity=90,
                      improvements=["Could briefly explain the mechanism."],
                      suggestedAnswer="Compare at the midpoint of a sorted range.")
    model = AsyncMock(side_effect=[first_pass, dict(verdict=verdict, quote=quote, note="State the mechanism.")])

    monkeypatch.setattr(evaluator.llm_service, "generate_json_response", model)
    request = AnswerEvaluationRequest(question="Explain how binary search works and give its complexity.",
        candidate_answer="It takes O(log n) time.")
    result = asyncio.run(evaluator.evaluate_candidate_answer(request))
    assert (result.answer_status, result.score) == (expected_status, expected_score)
    assert model.await_count == 2


def test_evidence_review_does_not_treat_missing_requested_details_as_false_claims(monkeypatch):
    from unittest.mock import AsyncMock

    question = "Design a rate limiter across replicas and explain coordination, expiry and client behavior."
    answer = "Each replica tracks request counts locally and responds with 429 above the limit."
    model = AsyncMock(side_effect=[
        dict(evidence=[answer], central_error={"claim": answer, "reason": "Check coordination.", "impact": "Requested coordination."},
             answer_status="PARTIAL", technicalAccuracy=30,
             relevance=70, clarity=90, missing_aspects=["Coordination", "Expiry"],
             suggestedAnswer="Use shared counters that expire at the end of each time window."),
        dict(verdict="FUNDAMENTAL", quote=answer, note="The answer does not explain coordination or expiry.",
             central_impact="Coordination was requested.", accuracy=30),
    ])
    monkeypatch.setattr(evaluator.llm_service, "generate_json_response", model)
    result = asyncio.run(evaluator.evaluate_candidate_answer(AnswerEvaluationRequest(question=question, candidate_answer=answer)))
    assert (result.answer_status, result.score) == ("PARTIAL", 48)
    assert result.missing_aspects == ["Coordination", "Expiry"]
    assert model.await_count == 2


def test_mixed_report_preserves_original_answer_scores_and_marks_only_new_answers():
    from app.services.report_generator import normalize_report_for_response

    questions = [{"id": "q1", "question": "First question"}, {"id": "q2", "question": "Second question"}]
    old = dict(score=65, technicalAccuracy=96, relevance=90, clarity=88, depth=12)
    new = dict(score=94, technicalAccuracy=96, relevance=90, clarity=88, depth=12,
               rubric_version="conceptual-v2", answer_status="CORRECT",
               improvements=["Optional: Include an example."])
    answers = [{"questionId": q["id"], "evaluation": ev} for q, ev in zip(questions, (old, new))]
    result = normalize_report_for_response(generate_final_report("s", "Engineer", "Technical", "Medium", questions, answers))
    assert result["overall_score"] == 80
    assert result["scores"]["rubric_version"] == "mixed"
    assert "depth" not in result["dimensions"]
    assert [(q["score"], q["rubric_version"]) for q in result["question_analysis"]] == [(65, None), (94, "conceptual-v2")]
    assert not result["skill_gaps"]


def test_saved_legacy_report_is_replayed_without_regrading_or_rewriting(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.api.v1.endpoints import interview

    legacy = {"overall_score": 65, "scores": {"depth": 12, "grade": "C"},
              "question_analysis": [{"question": "Old question", "score": 65, "depth": 12}]}
    read = AsyncMock(side_effect=[[{"id": "db-id", "status": "completed"}], [legacy]])
    persist = AsyncMock()
    monkeypatch.setattr(interview, "read_owned_rows", read)
    monkeypatch.setattr(interview, "persist_interview_report", persist)
    result = asyncio.run(interview._save_owned_report({"session_id": "session"},
        SimpleNamespace(token="token", user_id="user")))
    assert result["report"]["overall_score"] == 65
    assert result["report"]["grade"] == "C"
    assert result["report"]["dimensions"]["depth"] == 12
    persist.assert_not_called()


def test_resumed_session_versions_new_answers_without_regrading_saved_legacy_answer(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.api.v1.endpoints import evaluation as endpoint
    from app.schemas.evaluation import AnswerEvaluationResponse

    config = {"inference_engine": "local", "subject": "Java"}
    session = {"id": "db-id", "interview_config": config}
    question = {"id": "db-question", "question_id": "q1", "question_text": "What does Java collect?", "question_order": 1}
    data = dict(session_id="session", question_id="q1", question=question["question_text"],
                candidate_answer="Unreachable objects.")
    prior = dict(answer_text=data["candidate_answer"], score=69, technical_accuracy=98, relevance=93, depth=12, clarity=95)
    after = AnswerEvaluationResponse(score=96, technicalAccuracy=98, relevance=93, depth=12, clarity=95,
                                     rubric_version="conceptual-v2")
    model, update, insert = AsyncMock(return_value=after), AsyncMock(return_value=True), AsyncMock(return_value=True)
    monkeypatch.setattr(endpoint, "evaluate_candidate_answer", model)
    monkeypatch.setattr(endpoint, "update_interview_session", update)
    monkeypatch.setattr(endpoint, "persist_candidate_answer", insert)
    auth = SimpleNamespace(token="token", user_id="user")
    monkeypatch.setattr(endpoint, "read_owned_rows", AsyncMock(side_effect=[[session], [question], [prior]]))
    replay = asyncio.run(endpoint.evaluate_answer(AnswerEvaluationRequest(**data), auth))
    assert (replay.score, replay.rubric_version) == (69, None)
    model.assert_not_awaited()
    update.assert_not_awaited()
    insert.assert_not_awaited()

    monkeypatch.setattr(endpoint, "read_owned_rows", AsyncMock(side_effect=[[session], [question], []]))
    result = asyncio.run(endpoint.evaluate_answer(AnswerEvaluationRequest(**data), auth))
    assert (result.score, result.rubric_version) == (96, "conceptual-v2")
    assert update.call_args.args[2] == {"interview_config": {**config, "conceptual_question_ids": ["q1"]}}
    insert.assert_awaited_once()

    session = {**session, **update.call_args.args[2]}
    monkeypatch.setattr(endpoint, "read_owned_rows", AsyncMock(side_effect=[[session], [question], [dict(prior, score=96)]]))
    replay = asyncio.run(endpoint.evaluate_answer(AnswerEvaluationRequest(**data), auth))
    assert (replay.score, replay.rubric_version) == (96, "conceptual-v2")
    model.assert_awaited_once()
    insert.assert_awaited_once()
