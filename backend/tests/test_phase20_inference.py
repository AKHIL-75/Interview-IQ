"""Local preload, readiness, and context reuse regressions."""
import asyncio
from unittest.mock import AsyncMock
from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient
import httpx
import pytest

from app.core.config import settings
from app.core.inference import _use_engine
from app.main import app
from app.services import llm_service


@pytest.mark.parametrize("provider", ["ollama", "openrouter"])
def test_prewarm_only_uses_backend_owned_local_origin(monkeypatch, provider):
    real_client = httpx.AsyncClient
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200)

    def client(**options):
        assert options["follow_redirects"] is False
        assert options["trust_env"] is False
        assert options["timeout"] <= 90
        return real_client(transport=httpx.MockTransport(handler), **options)

    monkeypatch.setattr(llm_service.httpx, "AsyncClient", client)
    monkeypatch.setattr(settings, "OLLAMA_PREWARM_ENABLED", True)
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://local.example:11434")
    monkeypatch.setattr(settings, "AWS_OLLAMA_BASE_URL", "https://private.example")
    monkeypatch.setattr(settings, "LLM_PROVIDER", provider)
    with _use_engine("aws"):
        asyncio.run(llm_service.preload_local_ollama())
    if provider == "openrouter":
        assert requests == []
    else:
        assert len(requests) == 1
        assert str(requests[0].url) == "http://local.example:11434/api/generate"
        import json
        assert json.loads(requests[0].content) == {
            "model": settings.OLLAMA_MODEL, "stream": False, "keep_alive": settings.OLLAMA_KEEP_ALIVE}


def test_api_ready_during_prewarm_and_shutdown_cancels(monkeypatch):
    from app import main
    import threading
    ran, cancelled = threading.Event(), threading.Event()

    async def pending():
        ran.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    monkeypatch.setattr(settings, "OLLAMA_PREWARM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(main, "preload_local_ollama", pending)
    with TestClient(app) as api:
        assert ran.wait(2)
        assert api.get(settings.API_V1_PREFIX + "/health").status_code == 200
        assert not cancelled.is_set()
    assert cancelled.is_set()


def test_prewarm_deadline_is_not_a_generation_retry(monkeypatch):
    real_client = httpx.AsyncClient
    attempts = []

    async def handler(request):
        attempts.append(request)
        await asyncio.Future()

    monkeypatch.setattr(settings, "OLLAMA_PREWARM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "OLLAMA_TIMEOUT", .01)
    monkeypatch.setattr(llm_service.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    asyncio.run(llm_service.preload_local_ollama())
    assert len(attempts) == 1


@pytest.mark.parametrize(("engine", "expected_context"), [("local", None), ("aws", 2048)])
def test_resume_context_applies_only_to_existing_destination(engine, expected_context, monkeypatch):
    from fastapi import UploadFile
    from app.api.v1.endpoints.resume import parse_resume
    doc = Document()
    doc.add_paragraph("Synthetic candidate. Java and SQL. Academic inventory project.")
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    model = AsyncMock(side_effect=[
        llm_service.LLMResponseParseError("retry"),
        {"candidate_name": "Synthetic", "extracted_skills": ["Java", "SQL"]},
    ])
    monkeypatch.setattr(llm_service, "generate_json_response", model)
    with _use_engine(engine):
        result = asyncio.run(parse_resume(UploadFile(buf, filename="synthetic.docx"), auth=None))
    assert result.candidate_profile.extracted_skills == ["Java", "SQL"]
    assert [c.kwargs["num_ctx"] for c in model.await_args_list] == [expected_context, expected_context]
