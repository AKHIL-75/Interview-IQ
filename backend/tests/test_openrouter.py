"""Offline transport, accounting, timeout, and configuration contracts."""
import asyncio
import json
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.services import llm_service as llm, llm_usage

REAL_CLIENT = httpx.AsyncClient
SECRET = "sk-or-test-private-sentinel"
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"], "additionalProperties": False}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    # The mocked fallback contract must not depend on the developer's private .env.
    defaults = Settings(_env_file=None)
    for name in ("OPENROUTER_PRIMARY_MODEL", "OPENROUTER_FALLBACK_MODELS", "OPENROUTER_FREE_ONLY"):
        monkeypatch.setattr(settings, name, getattr(defaults, name))
    from pydantic import SecretStr
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", SecretStr(SECRET))


def completion(content='{"answer":"yes"}', **overrides):
    return {"model": settings.OPENROUTER_PRIMARY_MODEL, "provider": "TestProvider",
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            **overrides}


def transport(handler):
    return patch.object(llm.httpx, "AsyncClient", side_effect=lambda **kw:
        REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


def run(handler, **kwargs):
    async def invoke():
        with transport(handler), llm_usage.capture_usage() as events:
            result = await llm.generate_json_response("private synthetic prompt", **kwargs)
            return result, events
    return asyncio.run(invoke())


def test_openrouter_payload_and_success():
    def handler(request):
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer " + SECRET
        payload = json.loads(request.content)
        assert payload["models"] == settings.openrouter_models
        assert "model" not in payload
        assert payload["provider"] == dict(require_parameters=True, data_collection="deny", zdr=True, allow_fallbacks=True)
        assert payload["max_tokens"] == 700 and payload["temperature"] == .2
        assert payload["response_format"]["json_schema"]["schema"] == SCHEMA
        assert "think" not in payload and "num_ctx" not in payload
        return httpx.Response(200, json=completion(usage={"prompt_tokens": 17, "completion_tokens": 9, "cost": .0001}))
    result, events = run(handler, response_schema=SCHEMA, num_predict=700, temperature=.2, repeat_penalty=1.1)
    assert result == {"answer": "yes"}
    assert len(events) == 1
    event = events[0]
    assert (event["input_tokens"], event["output_tokens"], event["cost_usd"]) == (17, 9, .0001)
    assert event["cost_source"] == "provider_reported" and event["actual_provider"] == "TestProvider"


def test_server_fallback_is_one_http_request_and_actual_model_is_reported():
    calls = []
    def handler(request):
        calls.append(request)
        assert json.loads(request.content)["models"][1] == "openai/gpt-4.1-mini"
        # OpenRouter performs primary failure and fallback internally.
        return httpx.Response(200, json=completion(model="openai/gpt-4.1-mini"))
    _, events = run(handler)
    assert len(calls) == 1
    assert events[0]["actual_model"] == "openai/gpt-4.1-mini"
    assert events[0]["fallback_observed"] is True
    assert events[0]["internal_provider_attempts"] is None


@pytest.mark.parametrize("code,kind,status", [(401,"authentication",503), (402,"credits_or_budget",503),
    (403,"policy_or_budget",503), (429,"rate_limit",429), (503,"models_unavailable",503),
    (404,"model_unavailable",503), (400,"context_or_parameters",422), (413,"context_length",422), (408,"timeout",504)])
def test_errors_are_bounded_and_sanitized(code, kind, status, caplog):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(code, json={"error": {"message": SECRET + " private candidate answer"}})
    with pytest.raises(llm.OpenRouterError) as err:
        run(handler)
    assert err.value.kind == kind and err.value.status_code == status
    assert len(calls) == 1
    assert SECRET not in str(err.value) + caplog.text
    assert "private candidate answer" not in caplog.text


@pytest.mark.parametrize("content", ["not JSON", "null", "42", '"private answer"', '{"answer":7}', '{}'])
def test_invalid_json_or_schema(content):
    with pytest.raises(llm.LLMResponseParseError) as err:
        run(lambda r: httpx.Response(200, json=completion(content)), response_schema=SCHEMA)
    assert "private answer" not in str(err.value)


@pytest.mark.parametrize("body", [[], {}, {"choices": []}, completion(None), completion(""),
    {"error": {"code": 402, "message": SECRET}},
    completion(choices=[{"message": {"content": '{"answer":"yes"}'}, "finish_reason": "length"}])])
def test_invalid_envelopes_and_in_band_errors(body):
    with pytest.raises((llm.LLMResponseParseError, llm.OpenRouterError)):
        run(lambda r: httpx.Response(200, json=body))


def test_fallback_uses_same_schema_validation_and_accounts_for_billable_invalid_output():
    async def invoke():
        with transport(lambda r: httpx.Response(200, json=completion('{}', model="openai/gpt-4.1-mini",
                usage={"prompt_tokens": 10, "completion_tokens": 2, "cost": .001}))), llm_usage.capture_usage() as events:
            with pytest.raises(llm.LLMResponseParseError):
                await llm.generate_json_response("synthetic", response_schema=SCHEMA)
            assert events[0]["cost_usd"] == .001
            assert events[0]["status"] == "invalid_response" and events[0]["fallback_observed"] is True
    asyncio.run(invoke())


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": -1,"completion_tokens": True,"cost": "0.1"}])
def test_usage_unavailable_is_not_fabricated(usage):
    _, events = run(lambda r: httpx.Response(200, json=completion(usage=usage)))
    assert all(events[0][key] is None for key in ["input_tokens", "output_tokens", "cost_usd"])


def test_missing_actual_model_is_not_reported_as_requested_model():
    body = completion(); body.pop("model"); body.pop("provider")
    _, events = run(lambda r: httpx.Response(200, json=body))
    assert events[0]["actual_model"] is None and events[0]["actual_provider"] is None


def test_timeout_cancellation_and_total_operation_budget(monkeypatch):
    async def handler(r):
        await asyncio.sleep(5)
        return httpx.Response(200, json=completion())
    async def invoke():
        with transport(handler), llm_usage.capture_usage() as events:
            with pytest.raises(llm.LLMTimeoutError):
                await llm.generate_json_response("synthetic", timeout=.01)
            assert events[-1]["status"] == "timeout"
            task = asyncio.create_task(llm.generate_json_response("synthetic"))
            await asyncio.sleep(.01); task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert events[-1]["status"] == "cancelled"
            @llm_usage.operation("answer_evaluation")
            async def whole():
                await llm.generate_json_response("synthetic")
            monkeypatch.setattr(settings, "LLM_OPERATION_TIMEOUT_S", .01)
            with pytest.raises(llm.LLMTimeoutError): await whole()
            assert events[-1]["status"] == "timeout"
    asyncio.run(invoke())


def test_ollama_regression(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    def handler(r):
        body=json.loads(r.content)
        assert str(r.url).endswith("/api/generate") and "authorization" not in r.headers
        assert body["format"] == SCHEMA and body["think"] is False
        assert body["options"] == dict(num_predict=600, temperature=.1, repeat_penalty=1.1, repeat_last_n=64, num_ctx=2048)
        return httpx.Response(200, json={"response": '<think>reasoning</think>```json\n{"answer":"yes"}\n```',
            "model": "qwen3:4b", "prompt_eval_count": 12, "eval_count": 8})
    _, events = run(handler, response_schema=SCHEMA, think=False, num_predict=600, temperature=.1, repeat_penalty=1.1,num_ctx=2048)
    assert events[0]["input_tokens"] == 12 and events[0]["cost_usd"] is None
    with pytest.raises(llm.OllamaModelNotFoundError):
        run(lambda r:httpx.Response(404,text="not found"))


def test_configuration_defaults_and_secret_redaction():
    cfg = Settings(_env_file=None)
    assert cfg.LLM_PROVIDER == "ollama" and not cfg.OPENROUTER_BENCHMARK_ENABLED
    for values in [dict(LLM_PROVIDER="invalid"), dict(LLM_PROVIDER="openrouter",OPENROUTER_API_KEY=""),
        dict(OPENROUTER_BASE_URL="http://openrouter.ai/api/v1"), dict(OPENROUTER_BASE_URL="https://evil.test/api/v1"),
        dict(OPENROUTER_TIMEOUT_S=0), dict(LLM_OPERATION_TIMEOUT_S=float("inf")),
        dict(OPENROUTER_FALLBACK_MODELS="a/b,c/d,e/f"),dict(OPENROUTER_PRIMARY_MODEL="bad\nmodel"),
        dict(OPENROUTER_FREE_ONLY=True)]:
        with pytest.raises(ValidationError) as err:
            Settings(_env_file=None, OPENROUTER_API_KEY=SECRET, **{k:v for k,v in values.items() if k!="OPENROUTER_API_KEY"}) if values.get("OPENROUTER_API_KEY") != "" else Settings(_env_file=None,**values)
        assert SECRET not in str(err.value)
    free=Settings(_env_file=None, OPENROUTER_FREE_ONLY=True, OPENROUTER_PRIMARY_MODEL="openrouter/free",OPENROUTER_FALLBACK_MODELS="")
    assert free.openrouter_models == ["openrouter/free"]


def test_cloud_benchmark_requires_explicit_opt_in(monkeypatch):
    from scripts.benchmark_llm import check_live_enabled
    monkeypatch.setattr(settings,"OPENROUTER_BENCHMARK_ENABLED",False)
    with pytest.raises(ValueError): check_live_enabled("openrouter")
    monkeypatch.setattr(settings,"OPENROUTER_BENCHMARK_ENABLED",True)
    check_live_enabled("openrouter")
    with pytest.raises(ValueError): check_live_enabled("ollama")


def test_concurrent_capture_isolation_and_operation_names():
    @llm_usage.operation("jd_parse")
    async def one():
        with llm_usage.capture_usage() as events:
            await llm.generate_json_response("synthetic")
            await llm.generate_json_response("synthetic")
            return events
    async def invoke():
        with transport(lambda r: httpx.Response(200,json=completion())):
            a,b = await asyncio.gather(one(),one())
            assert a is not b and len(a)==len(b)==2
            assert [e["workflow_retry_index"] for e in a] == [0,1]
            assert all(e["operation"]=="jd_parse" for e in a+b)
    asyncio.run(invoke())


def test_usage_zero_and_safe_session_correlation():
    from types import SimpleNamespace
    @llm_usage.operation("answer_evaluation")
    async def evaluate(request):
        with llm_usage.capture_usage() as events:
            await llm.generate_json_response("synthetic")
            return events
    async def invoke():
        with transport(lambda r:httpx.Response(200,json=completion(usage={"prompt_tokens":0,"completion_tokens":0,"cost":0}))):
            events=await evaluate(SimpleNamespace(session_id="private-session",question_id="private-question"))
            assert events[0]["cost_usd"]==0 and events[0]["input_tokens"]==0
            assert "private-session" not in json.dumps(events) and "private-question" not in json.dumps(events)
            assert len(events[0]["session_ref"])==16 and len(events[0]["question_ref"])==16
    asyncio.run(invoke())


def test_no_http_attempt_when_key_missing(monkeypatch):
    from pydantic import SecretStr
    monkeypatch.setattr(settings,"OPENROUTER_API_KEY",SecretStr(""))
    async def invoke():
        with transport(lambda r:pytest.fail("must not send")),llm_usage.capture_usage() as events:
            with pytest.raises(llm.OpenRouterError):await llm.generate_json_response("synthetic")
            assert events[0]["http_attempts"]==0
    asyncio.run(invoke())


def test_untrusted_error_metadata_and_connection_errors():
    with pytest.raises(llm.OpenRouterError):run(lambda r:httpx.Response(200,json={"error":{"code":[]}}))
    def disconnected(request):raise httpx.ConnectError(SECRET,request=request)
    with pytest.raises(llm.OpenRouterError) as err:run(disconnected)
    assert SECRET not in str(err.value)
