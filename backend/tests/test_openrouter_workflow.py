"""Real orchestration with mocked HTTP inference; no accounts or live model calls."""
import asyncio
from collections import Counter
from unittest.mock import patch

from fastapi import HTTPException
import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.services import adaptive_interviewer as engine, llm_service, llm_usage
from scripts.benchmark_llm import offline_workflow, setup, REAL_CLIENT


@pytest.mark.parametrize("count", [5, 10, 15])
def test_actual_completed_workflow_counts(count):
    # Opening HR is deterministic. The repair path adds one resume retry, one
    # question retry and one separate reference-generation call per answer.
    for subject,repairs,expected in [(None,False,2*count+1),("Java",False,2*count+2),(None,True,3*count+3)]:
        result=asyncio.run(offline_workflow(count,subject,repairs))
        assert result["http_inference_attempts"]==expected
        assert result["completed_interviews"]==1 and result["answered_questions"]==count
        assert result["report_rows"]==count
        assert result["input_tokens"] is None and result["cost_usd"] is None
        assert result["calls_by_operation"]["answer_evaluation"]==count


def test_cloud_successful_fallback_through_entire_workflow(monkeypatch):
    # Explicit synthetic fallback configuration, independent of local free-only use.
    monkeypatch.setattr(settings,"OPENROUTER_PRIMARY_MODEL","qwen/qwen3-235b-a22b-2507")
    monkeypatch.setattr(settings,"OPENROUTER_FALLBACK_MODELS","openai/gpt-4.1-mini,google/gemini-2.5-flash")
    monkeypatch.setattr(settings,"OPENROUTER_FREE_ONLY",False)
    monkeypatch.setattr(settings,"OPENROUTER_API_KEY",SecretStr("synthetic-key"))
    result=asyncio.run(offline_workflow(5,provider_name="openrouter"))
    assert result["completed_interviews"]==1 and result["http_inference_attempts"]==11
    assert result["observed_fallback_responses"]==11
    assert all(e["actual_model"]==settings.openrouter_models[-1] for e in result["events"])


@pytest.mark.parametrize("code",[401,402,429,503])
def test_resume_does_not_retry_provider_failures(monkeypatch,code):
    monkeypatch.setattr(settings,"LLM_PROVIDER","openrouter")
    monkeypatch.setattr(settings,"OPENROUTER_API_KEY",SecretStr("synthetic-key"))
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(code,json={"error":{"message":"private"}})
    async def invoke():
        with patch.object(llm_service.httpx,"AsyncClient",side_effect=lambda **kw:
                REAL_CLIENT(transport=httpx.MockTransport(handler),**kw)),llm_usage.capture_usage() as events:
            with pytest.raises(HTTPException) as err: await setup()
            assert err.value.status_code==(429 if code==429 else 503)
            assert len(calls)==1 and len(events)==1
            assert events[0]["operation"]=="resume_parse"
    asyncio.run(invoke())


def test_question_content_retries_stop_at_existing_limit(monkeypatch):
    monkeypatch.setattr(settings,"LLM_PROVIDER","openrouter")
    monkeypatch.setattr(settings,"OPENROUTER_API_KEY",SecretStr("synthetic-key"))
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={"model":"openai/gpt-4.1-mini", "choices":[{"message":{"content":"invalid JSON"}}]})
    async def invoke():
        with patch.object(llm_service.httpx,"AsyncClient",side_effect=lambda **kw:
                REAL_CLIENT(transport=httpx.MockTransport(handler),**kw)),patch.object(engine,"prepare_semantic_history"),llm_usage.capture_usage() as events:
            with pytest.raises(llm_service.LLMResponseParseError):
                await engine.generate_single_next_question("NEXT_TOPIC","TECHNICAL_FUNDAMENTALS","Java","Java types","Medium","Technical","Engineer",subject="Java")
            assert len(calls)==engine.MAX_GENERATION_RETRIES+1==4
            assert [e["workflow_retry_index"] for e in events]==[0,1,2,3]
    asyncio.run(invoke())


def test_matching_makes_no_inference_requests(monkeypatch):
    from app.services import semantic_matcher
    from app.schemas.resume import CandidateProfile
    from app.schemas.job import JobProfile
    import numpy as np
    class Embeddings:
        def encode(self, values, **kwargs):
            return np.array([[1.,0.] if v.lower()=="java" else [0.,1.] for v in values])
    monkeypatch.setattr(semantic_matcher,"get_embedding_model",lambda:Embeddings())
    with llm_usage.capture_usage() as events:
        result=semantic_matcher.calculate_match_analysis(CandidateProfile(extracted_skills=["Java","SQL"]),JobProfile(required_skills=["Java","SQL"]))
    assert result.match_score==100 and events==[]
