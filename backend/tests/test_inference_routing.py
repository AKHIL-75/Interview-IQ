"""Real FastAPI routes and Ollama payloads with the network transport controlled."""
import asyncio
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.api.v1.endpoints import evaluation, interview
from app.core.auth import get_current_auth, get_optional_auth
from app.core.config import settings
from app.core.inference import ENGINE_HEADER, current_engine


@pytest.fixture
def system(monkeypatch, request):
    monkeypatch.setattr(settings, "INFERENCE_SERIAL_ADMISSION", getattr(request, "param", False))
    app = runpy.run_path(str(Path(__file__).parents[1] / "app/main.py"))["app"]
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "qwen3:4b")
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://local.test")
    monkeypatch.setattr(settings, "AWS_OLLAMA_BASE_URL", "https://aws.test")
    client = httpx.AsyncClient
    state = SimpleNamespace(app=app, calls=[], failure=None, barrier=None, client_class=client, model_response=None)

    async def upstream(req):
        host = req.url.host
        payload = json.loads(req.content) if req.content else {}
        state.calls.append((host, req.url.path, payload))
        assert host in {"local.test", "aws.test"}
        if state.failure == "timeout":
            raise httpx.ReadTimeout("synthetic private detail", request=req)
        if state.failure == "offline":
            raise httpx.ConnectError("synthetic private detail", request=req)
        if state.failure == "redirect":
            return httpx.Response(307, headers={"location": "https://invalid.test"})
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [] if state.failure else [{"name": "qwen3:4b"}]})
        assert req.url.path == "/api/generate" and req.method == "POST"
        assert payload["model"] == "qwen3:4b" and payload["stream"] is False
        if state.failure == "missing":
            return httpx.Response(404)
        if state.barrier is not None:
            await asyncio.wait_for(state.barrier.wait(), timeout=3)
        content = (state.model_response(payload) if state.model_response else
                   {"suggestedAnswer": "Transactions provide atomic changes on " + host.split(".")[0]})
        return httpx.Response(200, json={"model": "qwen3:4b", "response": json.dumps(content)})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs:
                        client(transport=httpx.MockTransport(upstream), **kwargs))
    state.api = lambda peer="guest": client(base_url="http://api.test/api/v1/",
        transport=httpx.ASGITransport(app=app, client=(peer, 1000)))
    return state


ANSWER = {"question": "What is an atomic transaction?", "candidate_answer": "I don't know"}


def test_concurrent_guest_routing_and_default(system):
    async def check():
        system.barrier = asyncio.Barrier(2)
        async with system.api("first") as first, system.api("second") as second:
            local, aws = await asyncio.gather(first.post("evaluation/evaluate", json=ANSWER),
                second.post("evaluation/evaluate", headers={ENGINE_HEADER: "aws"}, json=ANSWER))
            for response, engine in ((local, "local"), (aws, "aws")):
                assert response.status_code == 200
                assert response.json()["suggestedAnswer"].endswith(engine)
                assert response.json()["score"] == 0
            system.barrier = None
            again = await second.post("evaluation/evaluate", json=ANSWER)
            assert again.json()["suggestedAnswer"].endswith("local")
            assert len(system.calls) == 3 and current_engine() == "local"
    asyncio.run(check())


def test_staging_default_routes_implicit_requests_and_preserves_explicit_local(system, monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_INFERENCE_ENGINE", "aws")
    monkeypatch.setattr(settings, "AWS_OLLAMA_NUM_THREADS", 2)

    async def check():
        async with system.api() as api:
            for headers, engine in (({}, "aws"), ({ENGINE_HEADER: "local"}, "local"), ({}, "aws")):
                response = await api.post("evaluation/evaluate", json=ANSWER, headers=headers)
                assert response.status_code == 200
                assert response.json()["suggestedAnswer"].endswith(engine)
                assert system.calls[-1][2]["options"].get("num_thread") == (2 if engine == "aws" else None)
        assert current_engine() == "aws"

    asyncio.run(check())


@pytest.mark.parametrize("system", [True], indirect=True)
def test_staging_rejects_overlapping_inference_and_releases_on_cancel(system):
    async def check():
        async with system.api("first") as first, system.api("second") as second:
            system.barrier = asyncio.Barrier(2)
            pending = asyncio.create_task(first.post("evaluation/evaluate", json=ANSWER))
            try:
                async with asyncio.timeout(2):
                    while system.barrier.n_waiting != 1:
                        await asyncio.sleep(0)
                assert (await second.get("health")).status_code == 200
                busy = await second.post("job/parse", json={})
                assert busy.status_code == 429
                assert busy.headers["retry-after"] == "5"
                assert len(system.calls) == 1
            finally:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            system.barrier = None
            assert (await second.post("evaluation/evaluate", json=ANSWER)).status_code == 200

    asyncio.run(check())


def test_evaluation_evidence_review_stays_on_its_interview_destination(system):
    answer = {"question": "Explain binary search and its time complexity.", "candidate_answer": "It takes O(log n)."}

    def model_response(payload):
        if "verdict" in payload["format"]["properties"]:
            return {"verdict": "MAIN_GAP", "quote": "Explain binary search", "note": "Explain the halving step.",
                    "central_impact": "", "accuracy": 40}
        return dict(interpretation=answer["candidate_answer"], evidence=[answer["candidate_answer"]],
                    central_error=None, answer_status="CORRECT",
                    technicalAccuracy=95, relevance=90, clarity=90, improvements=["Explain the halving step."],
                    suggestedAnswer="Compare the midpoint and halve the remaining sorted range.")

    async def check():
        system.barrier = asyncio.Barrier(2)
        system.model_response = model_response
        async with system.api("first") as first, system.api("second") as second:
            responses = await asyncio.gather(first.post("evaluation/evaluate", json=answer),
                second.post("evaluation/evaluate", headers={ENGINE_HEADER: "aws"}, json=answer))
        assert all(r.status_code == 200 and r.json()["answer_status"] == "PARTIAL" for r in responses)
        for engine in ("local.test", "aws.test"):
            requests = [p["format"]["properties"] for host, path, p in system.calls if host == engine]
            assert len(requests) == 2 and "technicalAccuracy" in requests[0] and "verdict" in requests[1]
        assert current_engine() == "local"

    asyncio.run(check())


def test_availability_coalesces_and_never_generates(system):
    async def check():
        async with system.api() as api:
            responses = await asyncio.gather(*(api.get("inference/engines") for _ in range(8)))
            assert all(r.json() == {"local": True, "aws": True} for r in responses)
            assert all(r.headers["cache-control"] == "no-store" for r in responses)
            assert sorted(system.calls) == [("aws.test", "/api/tags", {}), ("local.test", "/api/tags", {})]
    asyncio.run(check())


@pytest.mark.parametrize("origin", ["", "file:///etc/passwd", "https://user:secret@private.test",
    "http://ollama.example.invalid:99999", "https://private.test/other", "http://169.254.169.254", "http://8.8.8.8"])
def test_unconfigured_or_invalid_aws_origin(system, monkeypatch, origin):
    monkeypatch.setattr(settings, "AWS_OLLAMA_BASE_URL", origin)
    async def check():
        async with system.api() as api:
            assert (await api.get("inference/engines")).json() == {"local": True, "aws": False}
            r = await api.post("evaluation/evaluate", headers={ENGINE_HEADER: "aws"}, json=ANSWER)
            assert r.status_code == 503
            assert system.calls == [("local.test", "/api/tags", {})]
    asyncio.run(check())


@pytest.mark.parametrize("values", [["other"], ["http://untrusted.test"], ["aws", "local"]])
def test_only_literal_single_destination_allowed(system, values):
    async def check():
        async with system.api() as api:
            r = await api.post("evaluation/evaluate", json=ANSWER, headers=[(ENGINE_HEADER, v) for v in values])
            assert r.status_code == 422 and not system.calls
            assert "untrusted" not in r.text
    asyncio.run(check())


@pytest.mark.parametrize("failure,status", [("offline", 503), ("timeout", 504), ("missing", 503)])
def test_unavailable_model_never_falls_back(system, failure, status):
    system.failure = failure
    async def check():
        async with system.api() as api:
            assert (await api.get("inference/engines")).json() == {"local": False, "aws": False}
            r = await api.post("evaluation/evaluate", headers={ENGINE_HEADER: "aws"}, json=ANSWER)
            assert r.status_code == status and "private" not in r.text and ".test" not in r.text
            assert [host for host, path, _ in system.calls if path == "/api/generate"] == ["aws.test"]
    asyncio.run(check())


def test_no_redirect_or_budget_reset_between_engines(system):
    system.failure = "redirect"
    async def check():
        async with system.api() as api:
            assert (await api.get("inference/engines")).json() == {"local": False, "aws": False}
            for engine in ["local", "aws", "local"]:
                r = await api.post("ai/test", headers={ENGINE_HEADER: engine}, json={})
            assert r.status_code == 429 and len(system.calls) == 4
    asyncio.run(check())


@pytest.mark.parametrize("engine", ["local", "aws"])
def test_pinned_engine_rejects_changed_provider_before_inference(system, monkeypatch, engine):
    from fastapi import HTTPException
    from app.core.inference import session_engine
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    with pytest.raises(HTTPException) as exc:
        with session_engine({"interview_config": {"inference_engine": engine}}):
            pytest.fail("Pinned sessions must keep their original provider")
    assert exc.value.status_code == 503 and not system.calls


def test_start_and_owned_evaluation_pin_saved_engine(system, monkeypatch):
    auth = SimpleNamespace(token="test-token", user_id="test-owner")
    save = AsyncMock(return_value={"id": "db-session"})
    monkeypatch.setattr(interview, "persist_interview_session", save)
    monkeypatch.setattr(interview, "persist_interview_question", AsyncMock(return_value={"id": "db-q"}))
    monkeypatch.setattr(evaluation, "persist_candidate_answer", AsyncMock(return_value=True))
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(evaluation, "update_interview_session", update)

    async def check():
        async with system.api() as api:
            # Use the normal auth gate before installing test-only identity dependencies.
            assert (await api.post("interview/start", headers={ENGINE_HEADER: "aws"}, json={})).status_code == 401
            system.app.dependency_overrides[get_current_auth] = lambda: auth
            system.app.dependency_overrides[get_optional_auth] = lambda: auth
            r = await api.post("interview/start", headers={ENGINE_HEADER: "aws"}, json={})
            assert r.status_code == 200
            config = save.await_args.kwargs["interview_config"]
            assert config["inference_engine"] == "aws"
            row = {"id": "db-session", "interview_config": config}
            question = {"id": "db-q", "question_id": "q1", "question_text": ANSWER["question"], "question_order": 1}

            async def rows(token, table, filters):
                assert token == "test-token"
                return {"interview_sessions": [row], "interview_questions": [question], "candidate_answers": []}[table]

            monkeypatch.setattr(evaluation, "read_owned_rows", rows)
            body = {**ANSWER, "session_id": r.json()["session_id"], "question_id": "q1"}
            r = await api.post("evaluation/evaluate", json=body, headers={ENGINE_HEADER: "local"})
            assert r.status_code == 409
            for engine in ("aws", "local"):
                r = await api.post("evaluation/evaluate", json=body)
                assert r.status_code == 200 and r.json()["suggestedAnswer"].endswith(engine)
                row.pop("interview_config", None)  # Existing sessions predate the selector.
            assert [h for h, p, _ in system.calls if p == "/api/generate"] == ["aws.test", "local.test"]
            update.assert_awaited_once()
            assert update.await_args.args[2]["interview_config"] == {"conceptual_question_ids": ["q1"]}
    asyncio.run(check())


def test_entire_concurrent_interviews_keep_their_own_upstream(system, monkeypatch):
    from app.core.inference import session_engine
    from app.services import adaptive_interviewer, llm_usage
    from scripts.benchmark_llm import OfflineProvider, workflow

    monkeypatch.setattr(adaptive_interviewer, "prepare_semantic_history", lambda *args: None)
    monkeypatch.setattr(adaptive_interviewer, "semantic_duplicate", lambda *args: False)
    providers = {host: OfflineProvider(subject="Java") for host in ("local.test", "aws.test")}
    observed = {host: [] for host in providers}

    async def upstream(request):
        host = request.url.host
        assert request.url.path == "/api/generate"
        assert json.loads(request.content)["model"] == "qwen3:4b"
        observed[host].append(llm_usage._operation.get())
        await asyncio.sleep(0)
        return providers[host](request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs:
                        system.client_class(transport=httpx.MockTransport(upstream), **kwargs))

    async def run(engine):
        with session_engine({"interview_config": {"inference_engine": engine}}):
            return await workflow(5, subject="Java")

    async def check():
        results = await asyncio.gather(run("local"), run("aws"))
        assert all(r == {"completed_interviews": 1, "answered_questions": 5, "report_rows": 5} for r in results)
        assert observed["local.test"] == observed["aws.test"]
        assert {"resume_parse", "jd_parse", "answer_evaluation", "initial_question", "adaptive_question"} <= set(observed["aws.test"])
        assert current_engine() == "local"
    asyncio.run(check())
