"""Project grounding regression tests; Qwen and persistence are mocked, never live."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.project_context import resolve_project, explicit_project_question, named_projects
from app.services import adaptive_interviewer as engine, evaluator, persistence_service
from app.services.question_generator import generate_interview_questions, generate_fallback_question
from app.prompts.evaluation_prompts import build_evaluation_prompt
from app.schemas.adaptive import InterviewStartRequest, AdaptiveNextQuestionRequest
from app.schemas.interview import QuestionGenerationRequest
from app.schemas.resume import CandidateProfile
from app.schemas.job import JobProfile
from app.schemas.evaluation import AnswerEvaluationRequest, AnswerEvaluationResponse
from app.api.v1.endpoints import evaluation as endpoint

PROJECTS = [
    {"name": "GardenTrack", "description": "A planting calendar with reminders.", "technologies": ["Python"]},
    {"name": "RouteMap", "description": "A route planning tool with saved journeys.", "technologies": ["Java"]},
]
VAGUE = "Can you describe how your specific contribution impacted the platform's user experience?"


@pytest.fixture(autouse=True)
def offline_model(monkeypatch):
    model = AsyncMock(return_value={"question": VAGUE, "lead_in": "Let's discuss the implementation."})
    monkeypatch.setattr(engine.llm_service, "generate_json_response", model)
    monkeypatch.setattr(engine, "semantic_duplicate", lambda *args: False)
    return model


def generate(**kwargs):
    args = dict(decision="NEXT_TOPIC", stage="PROJECT", target_skill="GardenTrack",
                target_concept="overview and contribution", difficulty="Medium", category="Technical",
                role="Engineer", project_name="GardenTrack", project_context=PROJECTS[0])
    args.update(kwargs)
    return asyncio.run(engine.generate_single_next_question(**args))[0]


@pytest.mark.parametrize("name", ["GardenTrack", "RouteMap", "Research Atlas"])
def test_contribution_uses_each_candidates_actual_name(name, offline_model):
    project = {"name": name, "description": "A tool for organizing notes.", "technologies": ["Python"]}
    question = generate(project_name=name, project_context=project, target_skill=name)
    assert question.question == f"For your {name} project, can you describe how your specific contribution impacted the platform's user experience?"
    assert question.topic == name
    prompt = offline_model.call_args.kwargs["prompt"]
    assert project["description"] in prompt and "organizing notes" not in question.question
    assert "Interview-IQ" not in question.question and "Cinemaverse" not in question.question
    assert all("overview" not in aspect for aspect in question.expected_aspects)


def test_already_named_question_is_not_prefixed_twice(offline_model):
    text = "For your GardenTrack project, explain how you implemented reminders."
    offline_model.return_value = {"question": text}
    assert generate().question == text


@pytest.mark.parametrize("stage", ["TECHNICAL_FUNDAMENTALS", "PROJECT"])
@pytest.mark.parametrize("text", ["What is polymorphism in Java?", "How does polymorphism work in Java?", "Define a transaction."])
def test_unrelated_conceptual_question_stays_natural(stage, text, offline_model):
    offline_model.return_value = {"question": text}
    assert generate(stage=stage).question == text
    if stage == "TECHNICAL_FUNDAMENTALS":
        assert "Project in discussion" not in offline_model.call_args.kwargs["prompt"]


def test_subject_question_never_receives_active_project(offline_model):
    offline_model.return_value = {"question": "What is polymorphism in Java?"}
    assert generate(stage="TECHNICAL_FUNDAMENTALS", subject="Java").question == "What is polymorphism in Java?"
    assert "GardenTrack" not in offline_model.call_args.kwargs["prompt"].split("Target Topic:")[0]


def test_general_system_question_is_not_mistaken_for_resume_project(offline_model):
    text = "How does the system allocate virtual memory?"
    offline_model.return_value = {"question": text}
    assert generate(stage="TECHNICAL_FUNDAMENTALS").question == text


def test_ambiguous_project_followup_does_not_assume_active_project(offline_model):
    question = generate(stage="BEHAVIORAL", category="HR", decision="TARGETED_FOLLOW_UP",
        previous_question="How did you handle a conflict on your project?", project_name=None, project_context=None)
    assert question.question.startswith("Choose a project you worked on.")


def test_followup_resolution_uses_answer_then_previous_question_not_first_project():
    assert resolve_project(PROJECTS, active_project=PROJECTS[0], previous_question="Explain RouteMap's design.", follow_up=True) == PROJECTS[1]
    assert resolve_project(PROJECTS, previous_question="Explain GardenTrack's design.", candidate_answer="I actually built RouteMap.", follow_up=True) == PROJECTS[1]
    assert resolve_project(PROJECTS, previous_question="Compare GardenTrack and RouteMap.", follow_up=True) is None
    assert resolve_project(PROJECTS, topic="GardenTrack", candidate_answer="I worked on GardenTrack and RouteMap.", follow_up=True) is None
    assert resolve_project(PROJECTS, follow_up=True, active_project=PROJECTS[0]) is None


@pytest.mark.parametrize("projects", [[], [{"name": "Untitled Project"}], PROJECTS])
def test_missing_or_ambiguous_identity_discards_unsupported_details(projects):
    project = resolve_project(projects)
    assert project is None
    text = explicit_project_question("How did your GhostApp platform achieve 50% faster Redis queries?", project, required=True)
    assert text.startswith("Choose a project you worked on.")
    assert all(value not in text for value in ["GhostApp", "Redis", "50%", "GardenTrack", "RouteMap"])


def test_missing_project_generation_is_general_not_placeholder(offline_model):
    question = generate(project_name="Untitled Project", project_context=None, target_skill="Key Project")
    assert question.question.startswith("Choose a project")
    assert "Untitled" not in question.question


def test_real_adaptive_flow_retains_answer_project_and_supplied_details(offline_model):
    async def run():
        started = await engine.process_adaptive_start(InterviewStartRequest(
            candidate_profile={"key_projects": PROJECTS}, question_count=10))
        started.interview_state.update(current_stage="PROJECT", current_topic="RouteMap", questions_asked=4)
        started.interview_plan["active_project"] = PROJECTS[0]
        previous = "For your RouteMap project, explain how you structured the route data."
        request = AdaptiveNextQuestionRequest(
            previous_question=previous, candidate_answer="I used Java for RouteMap and stored journeys separately.",
            evaluation=dict(score=64, technicalAccuracy=55, relevance=80, depth=100, clarity=70, answer_status="PARTIAL"),
            current_topic="RouteMap", relevant_skills=["RouteMap"], question_history=[previous],
            interview_plan=started.interview_plan, interview_state=started.interview_state)
        return await engine.process_adaptive_next_question(request)
    result = asyncio.run(run())
    assert result.isFollowUp
    assert "RouteMap" in result.question.question and "GardenTrack" not in result.question.question
    assert result.question.topic == "RouteMap"
    assert result.interview_plan["active_project"]["name"] == "RouteMap"
    prompt = offline_model.call_args.kwargs["prompt"]
    assert "saved journeys" in prompt and "stored journeys separately" in prompt


def test_bulk_generation_also_fixes_project_question(offline_model):
    offline_model.return_value = {"questions": [{"question": VAGUE, "topic": "RouteMap", "stage": "PROJECT"}]}
    request = QuestionGenerationRequest(candidate_profile=CandidateProfile(key_projects=PROJECTS),
        job_profile=JobProfile(role_title="Engineer", required_skills=["Python"]), question_count=5)
    result = asyncio.run(generate_interview_questions(request))
    project_questions = [q for q in result.questions if "specific contribution" in q.question]
    assert len(project_questions) == 1
    assert "RouteMap" in project_questions[0].question
    assert "Cinemaverse" not in offline_model.call_args.kwargs["prompt"]


def test_project_fallback_does_not_assign_a_frontend_technology_to_backend():
    question = generate_fallback_question(stage="PROJECT", index=3, candidate_profile=CandidateProfile(key_projects=[
        {"name": "GardenTrack", "technologies": ["React"]}]), job_profile=JobProfile(role_title="Engineer"),
        difficulty="Medium", interview_type="Technical", analysis=None, used_topics=set())
    assert "GardenTrack" in question.question and "backend" not in question.question


def test_evaluation_prompt_and_non_answer_reference_use_the_actual_question(offline_model):
    question = generate()
    request = AnswerEvaluationRequest(question=question.question, candidate_answer="I don't know", stage="PROJECT",
        topic=question.topic, expected_answer="; ".join(question.expected_aspects))
    prompt = build_evaluation_prompt(request)
    assert f"=== QUESTION ===\n{question.question}" in prompt
    assert "A topic heading or reference concept must not broaden the question" in prompt
    offline_model.return_value = {"suggestedAnswer": "Illustrative example: For GardenTrack, I implemented reminders, tested their timing and documented how to use them."}
    response = asyncio.run(evaluator.evaluate_candidate_answer(request))
    assert response.suggestedAnswer != question.question
    assert "GardenTrack" in response.suggestedAnswer
    assert "MongoDB" not in response.suggestedAnswer


def test_saved_evaluation_uses_owned_canonical_text_and_expected_aspects():
    question = generate()
    current = dict(id="db-q", question_id="q1", question_text=question.question, question_order=1,
        stage="PROJECT", topic="GardenTrack", expected_aspects=question.expected_aspects)
    read = AsyncMock(side_effect=[[dict(id="db-session", status="active")], [current], []])
    result = AnswerEvaluationResponse(score=60, technicalAccuracy=60, relevance=60, depth=60, clarity=60,
        strengths=[], improvements=[], suggestedAnswer="Explain your actual work on GardenTrack.")
    evaluate = AsyncMock(return_value=result)
    request = AnswerEvaluationRequest(session_id="session", question_id="q1", question=question.question,
        candidate_answer="I implemented reminders.", expected_answer="Invented project and metrics", relevant_skills=["Wrong project"])
    with patch.object(endpoint, "read_owned_rows", read), patch.object(endpoint, "evaluate_candidate_answer", evaluate), \
         patch.object(endpoint, "persist_candidate_answer", AsyncMock(return_value={"id": "saved"})):
        response = asyncio.run(endpoint.evaluate_answer(request, SimpleNamespace(user_id="owner", token="test-token")))
    supplied = evaluate.call_args.args[0]
    assert supplied.question == question.question
    assert supplied.expected_answer == "; ".join(question.expected_aspects)
    assert supplied.relevant_skills == ["GardenTrack"]
    assert response.suggestedAnswer == result.suggestedAnswer


def test_persistence_saves_the_same_canonical_text():
    question = generate()
    post = AsyncMock(return_value=SimpleNamespace(status_code=201, json=lambda: [{"id": "saved"}]))
    with patch.object(persistence_service.settings, "SUPABASE_URL", "https://mock.invalid"), \
         patch.object(persistence_service, "get_question_db_uuid", AsyncMock(return_value=None)), \
         patch.object(persistence_service.httpx, "AsyncClient") as client:
        client.return_value.__aenter__.return_value.post = post
        asyncio.run(persistence_service.persist_interview_question("test-token", "session", question.model_dump(), 2, "db-session"))
    assert post.call_args.kwargs["json"]["question_text"] == question.question
