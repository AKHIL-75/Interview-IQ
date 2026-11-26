"""Offline error diagnostics: synthetic credentials, mocked responses, no retries."""
import asyncio
import json
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.services import llm_service as llm, llm_usage

REAL_CLIENT = httpx.AsyncClient
SECRET = "synthetic-diagnostics-private-key"
PROMPT = "Synthetic resume CanaryResume; job CanaryJob; answer CanaryAnswer."


@pytest.fixture(autouse=True)
def free_only(monkeypatch):
    for name, value in {"LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": SecretStr(SECRET),
                        "OPENROUTER_PRIMARY_MODEL": "openrouter/free",
                        "OPENROUTER_FALLBACK_MODELS": "", "OPENROUTER_FREE_ONLY": True}.items():
        monkeypatch.setattr(settings, name, value)


def failure(caplog, status=429, body=None, headers=None, text=None):
    caplog.set_level("INFO")
    calls = []
    def handler(request):
        calls.append(request)
        assert json.loads(request.content)["models"] == ["openrouter/free"]
        return httpx.Response(status, headers=headers,
                              **({"text": text} if text is not None else {"json": body}))
    async def invoke():
        with patch.object(llm.httpx, "AsyncClient", side_effect=lambda **kw:
                REAL_CLIENT(transport=httpx.MockTransport(handler), **kw)), llm_usage.capture_usage() as events:
            with pytest.raises(llm.OpenRouterError) as err:
                await llm.generate_json_response(PROMPT)
            return err.value, events
    error, events = asyncio.run(invoke())
    assert len(calls) == len(events) == 1
    assert events[0]["http_status"] == status
    records = [r.getMessage().removeprefix("openrouter_error ") for r in caplog.records
               if r.name == llm.__name__ and r.getMessage().startswith("openrouter_error ")]
    assert len(records) == 1
    assert SECRET not in caplog.text and PROMPT not in caplog.text
    return json.loads(records[0]), error


def test_upstream_429_with_metadata(caplog):
    diagnostic, error = failure(caplog, body={"error": {
        "code": 429, "message": "Provider returned error.", "metadata": {
            "provider_name": "Phala", "raw": json.dumps({"error": {
                "code": "RESOURCE_EXHAUSTED", "type": "rate_limit_error",
                "message": "Rate limit exceeded. Please retry later."}})}}},
        headers={"Retry-After": "60"})
    assert diagnostic == {"http_status": 429, "error_code": 429, "error_type": None,
        "error_message": "Provider returned error.", "provider_error_code": "RESOURCE_EXHAUSTED",
        "provider_error_type": "rate_limit_error",
        "provider_error_message": "Rate limit exceeded. [redacted]", "retry_after": "60"}
    assert error.kind == "rate_limit" and error.status_code == 429
    assert str(error) == "OpenRouter request failed (rate_limit)."
    assert set(vars(error)) == {"kind", "status_code"}


def test_429_without_metadata(caplog):
    diagnostic, _ = failure(caplog, body={"error": {
        "code": "rate_limit_exceeded", "type": "rate_limit_error", "message": "Too many requests."}},
        headers={"Retry-After": "1"})
    assert diagnostic["error_code"] == "rate_limit_exceeded"
    assert diagnostic["error_type"] == "rate_limit_error"
    assert diagnostic["error_message"] == "Too many requests."
    assert diagnostic["provider_error_code"] is None
    assert diagnostic["provider_error_type"] is None
    assert diagnostic["provider_error_message"] is None


def test_non_429_keeps_existing_public_error_mapping(caplog):
    diagnostic, error = failure(caplog, status=401, body={"error": {
        "code": 401, "type": "authentication_error", "message": "Invalid API key."}})
    assert diagnostic["http_status"] == diagnostic["error_code"] == 401
    assert diagnostic["error_type"] == "authentication_error"
    assert diagnostic["error_message"] == "Invalid API key."
    assert error.kind == "authentication" and error.status_code == 503
    assert str(error) == "OpenRouter request failed (authentication)."


def test_missing_retry_after_is_explicitly_unavailable(caplog):
    diagnostic, _ = failure(caplog, body={"error": {"code": 429}})
    assert diagnostic["retry_after"] is None


def test_http_date_retry_after_is_retained(caplog):
    date = "Mon, 26 Oct 2026 16:30:00 GMT"
    diagnostic, _ = failure(caplog, body={}, headers={"Retry-After": date})
    assert diagnostic["retry_after"] == date


@pytest.mark.parametrize("value", ["secret-header-value", "60\r\nAuthorization: private", "9" * 100,
                                  "Mon, 99 Oct 2026 16:30:00 GMT"])
def test_untrusted_retry_after_is_not_logged(caplog, value):
    diagnostic, _ = failure(caplog, body={}, headers={"Retry-After": value})
    assert diagnostic["retry_after"] is None
    assert value not in caplog.text


def test_sensitive_echoes_in_all_error_fields_are_suppressed(caplog):
    private = SECRET + " Authorization: Bearer private-token " + PROMPT
    message = "Rate limit exceeded.\r\n" + private + "x" * 2000
    diagnostic, _ = failure(caplog, body={"error": {
        "code": private, "type": private, "message": message,
        "metadata": {"request_body": private, "raw": json.dumps({"error": {
            "code": private, "type": private, "message": message}})}}},
        headers={"Authorization": private, "X-Private": private})
    assert diagnostic["error_message"] == "Rate limit exceeded. [redacted]"
    assert diagnostic["provider_error_message"] == "Rate limit exceeded. [redacted]"
    for key in ("error_code", "error_type", "provider_error_code", "provider_error_type"):
        assert diagnostic[key] == "[redacted]"
    for forbidden in ("CanaryResume", "CanaryJob", "CanaryAnswer", "Authorization", "private-token", "request_body"):
        assert forbidden not in caplog.text
    assert all(len(v) <= 160 for k, v in diagnostic.items() if k.endswith("message") and v)


def test_unrecognized_prose_is_not_logged_even_without_secret_patterns(caplog):
    diagnostic, _ = failure(caplog, body={"error": {"message": "CanaryResume CanaryJob CanaryAnswer"}})
    assert diagnostic["error_message"] == "[redacted]"
    assert "CanaryResume" not in caplog.text


def test_non_200_attribution_cannot_bypass_sanitization(caplog):
    diagnostic, _ = failure(caplog, body={"model": "CanaryResume", "provider": SECRET,
        "error": {"code": 429}, "usage": {"prompt_tokens": 1, "completion_tokens": 0, "cost": 0}})
    assert diagnostic["http_status"] == 429
    assert "CanaryResume" not in caplog.text
    usage = next(json.loads(r.getMessage().removeprefix("llm_attempt ")) for r in caplog.records
                 if r.name == "app.llm_usage")
    assert usage["actual_model"] is None and usage["actual_provider"] is None
    assert usage["input_tokens"] == 1 and usage["cost_usd"] == 0


@pytest.mark.parametrize("raw", [None, [], 123, "not JSON", "[", "x" * 8193,
    {"error": []}, {"code": 429, "type": "rate_limit_error", "message": "Rate limit exceeded."}])
def test_malformed_or_direct_metadata_cannot_break_error_handling(caplog, raw):
    diagnostic, error = failure(caplog, body={"error": {"metadata": {"raw": raw}}})
    assert error.kind == "rate_limit" and diagnostic["http_status"] == 429
    if isinstance(raw, dict) and "code" in raw:
        assert diagnostic["provider_error_code"] == 429


@pytest.mark.parametrize("body", [None, [], {"error": []}, {"error": {"code": True, "type": {}}}])
def test_missing_or_malformed_error_fields_are_ignored(caplog, body):
    diagnostic, error = failure(caplog, body=body)
    assert diagnostic["error_code"] is None and diagnostic["error_type"] is None
    assert error.kind == "rate_limit"


def test_non_json_error_body_is_never_logged(caplog):
    diagnostic, error = failure(caplog, status=503, text=SECRET + PROMPT,
                                headers={"Retry-After": "30"})
    assert diagnostic["http_status"] == 503 and diagnostic["retry_after"] == "30"
    assert diagnostic["error_message"] is None
    assert error.kind == "models_unavailable" and error.status_code == 503
