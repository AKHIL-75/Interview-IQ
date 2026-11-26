"""Exact synthetic answer through the real evaluator and persistence adapters."""
import asyncio
import json
import time
from uuid import UUID
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.auth import AuthUser, get_optional_auth
from app.core.config import settings
from app.api.v1.endpoints import evaluation, interview
from app.services import evaluator, persistence_service as db
from app.services.performance import trace

ANSWER = "At Quartz Harbor, I used a B-tree index on order_id; the canary phrase is violet comet 47."
QUESTION = "How does a SQL index work, and what trade-offs does it introduce?"


def test_exact_answer_request_prompt_database_report_and_stale_attempt(monkeypatch):
    session = dict(id="session-db", session_id="stage3", role="Engineer", interview_type="Technical",
                   difficulty="Medium", question_count=5, status="active")
    question = dict(id="question-db", session_id="session-db", question_id="q1", question_order=1,
                    question_text=QUESTION, category="Technical", topic="SQL", difficulty="Medium")
    rows = {"interview_sessions": [session], "interview_questions": [question], "candidate_answers": [], "interview_reports": []}
    writes, prompts = [], []
    def transport(request):
        table = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            result = rows[table]
            for key, value in request.url.params.multi_items():
                if value.startswith("eq."):
                    result = [row for row in result if str(row.get(key)) == value[3:]]
            return httpx.Response(200, json=result)
        payload = json.loads(request.content)
        if request.method == "PATCH":
            session.update(payload)
            return httpx.Response(200, json=[session])
        writes.append((table, payload))
        rows[table].append(payload)
        return httpx.Response(201, json=[payload])
    real_client = httpx.AsyncClient
    monkeypatch.setattr(db.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(transport), **kwargs))
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://synthetic.invalid")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "synthetic-anon")
    async def model(prompt, **kwargs):
        prompts.append(prompt)
        assert ANSWER in prompt
        return dict(technicalAccuracy=75, relevance=80, depth=65, clarity=90, answer_status="PARTIAL",
                    strengths=["Specific example"], improvements=["Discuss write costs"],
                    suggestedAnswer="A different reference answer.", candidate_answer="LLM paraphrase must be ignored")
    monkeypatch.setattr(evaluator.llm_service, "generate_json_response", model)
    auth = AuthUser(UUID(int=47), "synthetic-auth")
    app = FastAPI(); app.include_router(evaluation.router)
    app.dependency_overrides[get_optional_auth] = lambda: auth
    client = TestClient(app)
    payload = dict(session_id="stage3", question_id="q1", question=QUESTION, candidate_answer=ANSWER, difficulty="Medium", topic="SQL")
    response = client.post("/evaluate", json=payload)
    assert response.status_code == 200
    assert len(prompts) == 1
    saved = rows["candidate_answers"][0]
    assert saved["answer_text"] == ANSWER
    assert saved["score"] == 78
    assert (saved["technical_accuracy"], saved["relevance"], saved["depth"], saved["clarity"]) == (75, 80, 65, 90)
    assert saved["question_id"] == "question-db" and saved["session_id"] == "session-db"
    assert saved["suggested_answer"] != ANSWER
    # A late/different attempt must never overwrite the committed answer.
    stale = client.post("/evaluate", json={**payload, "candidate_answer": "Late amber otter attempt"})
    assert stale.status_code == 409 and len(rows["candidate_answers"]) == 1
    assert client.post("/evaluate", json=payload).status_code == 200
    assert len(prompts) == 1
    capture = {"start": time.perf_counter(), "stages": []}
    token = trace.set(capture)
    try:
        result = asyncio.run(interview._save_owned_report({"session_id": "stage3", "candidate_answer": "Untrusted client replacement"}, auth))
    finally:
        trace.reset(token)
    assert result["persisted"]
    report = rows["interview_reports"][0]
    assert report["overall_score"] == 78
    assert report["scores"]["grade"] == "B"
    assert result["report"]["overall_score"] == 78
    assert report["scores"]["rubric_version"] == "conceptual-v2"
    assert report["question_analysis"][0]["candidate_answer"] == ANSWER
    assert result["report"]["question_analysis"][0]["candidate_answer"] == ANSWER
    assert rows["candidate_answers"][0]["answer_text"] == ANSWER
    assert ANSWER not in json.dumps(capture)


def test_semantic_cache_preserves_threshold_and_only_encodes_missing(monkeypatch):
    import numpy as np
    from app.services import question_policy as policy, semantic_matcher as matcher
    calls = []
    class Model:
        def encode(self, texts, **kwargs):
            calls.append(texts)
            assert kwargs == dict(convert_to_numpy=True, normalize_embeddings=True)
            return np.array([[1., 0.] if text != "different" else [0., 1.] for text in texts])
    model = Model()
    monkeypatch.setattr(matcher, "get_embedding_model", lambda: model)
    turn = {}
    policy.prepare_semantic_history(["history"], turn)
    assert policy.semantic_duplicate("same meaning", ["history"], turn)
    assert not policy.semantic_duplicate("different", ["history"], turn)
    assert policy.semantic_duplicate("same meaning", ["history"], turn)
    assert calls == [["history"], ["same meaning"], ["different"]]
    assert policy.semantic_duplicate("same meaning", ["history"], {})
    assert calls[-1] == ["same meaning", "history"]
