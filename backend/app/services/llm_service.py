"""Single HTTP boundary for Ollama and explicitly enabled OpenRouter inference."""
import asyncio
from functools import lru_cache
import os
from email.utils import format_datetime, parsedate_to_datetime
import json
import logging
import re
import time

import httpx
from jsonschema import Draft202012Validator, ValidationError, SchemaError

from app.core.config import settings
from app.core.inference import current_engine, engine_origin
from app.services.performance import timed, span, metric
from app.services import llm_usage

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _default_verified_context():
    # HTTPX constructs TLS contexts even for http:// requests. Only this
    # immutable trust configuration is reused. Clients and cookies stay local.
    return httpx.create_ssl_context()


async def preload_local_ollama():
    """Give the configured local runner time to load before the first request."""
    if not settings.OLLAMA_PREWARM_ENABLED or settings.LLM_PROVIDER != "ollama":
        return
    origin = engine_origin("local")
    if not origin:
        return
    started = time.perf_counter()
    timeout = min(settings.OLLAMA_TIMEOUT, 90.0)
    payload = {"model": settings.OLLAMA_MODEL, "stream": False, "keep_alive": settings.OLLAMA_KEEP_ALIVE}

    async def load():
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST", origin + "/api/generate", json=payload) as response:
                return response.status_code == 200

    try:
        loaded = await asyncio.wait_for(load(), timeout)
    except (httpx.HTTPError, httpx.InvalidURL, asyncio.TimeoutError, ValueError):
        loaded = False
    logger.info("ollama_prewarm ready=%s duration_ms=%.1f",
                loaded, (time.perf_counter() - started) * 1000)


class LLMServiceError(Exception):
    """Sanitized inference failure."""


class OllamaConnectionError(LLMServiceError):
    pass


class OllamaModelNotFoundError(LLMServiceError):
    pass


class LLMTimeoutError(LLMServiceError):
    pass


class OllamaTimeoutError(LLMTimeoutError):
    pass


class LLMResponseParseError(LLMServiceError):
    pass


class OpenRouterError(LLMServiceError):
    """Only a fixed category/status escapes; never retain upstream error text."""
    def __init__(self, kind, status_code=503):
        self.kind = kind
        self.status_code = status_code
        super().__init__(f"OpenRouter request failed ({kind}).")


def _cloud_error(code):
    code = code if isinstance(code, int) and not isinstance(code, bool) else None
    categories = {400: ("context_or_parameters", 422), 401: ("authentication", 503),
                  402: ("credits_or_budget", 503), 403: ("policy_or_budget", 503),
                  404: ("model_unavailable", 503), 408: ("timeout", 504),
                  413: ("context_length", 422), 422: ("context_or_parameters", 422),
                  429: ("rate_limit", 429), 502: ("upstream_failure", 503),
                  503: ("models_unavailable", 503), 504: ("timeout", 504)}
    return OpenRouterError(*categories.get(code, ("provider_failure", 503)))


def _diagnostic_label(value):
    # These fields are also untrusted: a character whitelist alone permits keys
    # and short candidate answers. Retain only known machine error labels/codes.
    labels = {"rate_limit", "rate_limit_error", "rate_limit_exceeded", "too_many_requests",
              "resource_exhausted", "quota_exceeded", "insufficient_quota",
              "invalid_request_error", "invalid_api_key", "authentication_error",
              "permission_denied", "permission_error", "context_length_exceeded",
              "model_not_found", "not_found_error", "api_error", "server_error",
              "internal_error", "service_unavailable", "overloaded_error"}
    if type(value) is int and 0 <= value <= 599:
        return value
    if isinstance(value, str):
        if value.lower() in labels or re.fullmatch(r"[1-5][0-9]{2}", value):
            return value
        return "[redacted]"
    return None


def _diagnostic_message(value):
    if not isinstance(value, str):
        return None
    # Do not attempt to scrub arbitrary prose: providers can echo fragments of
    # resumes, answers, credentials, etc. Only retain an operational prefix and
    # replace the entire unfamiliar remainder. Never serialize raw metadata.
    text = " ".join(value[:1024].split())
    match = re.match(r"(?:rate limit exceeded|too many requests|quota exceeded|"
                     r"temporarily rate-limited upstream|invalid api key|"
                     r"authentication failed|service unavailable|internal server error|"
                     r"provider returned error|context length exceeded)"
                     r"(?:[.!]|$)", text, flags=re.IGNORECASE)
    safe = text[:match.end()] if match else "[redacted]"
    if match and (text[match.end():] or len(value) > 1024):
        safe += " [redacted]"
    return safe[:160]


def _diagnostic_retry_after(value):
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"[0-9]{1,9}", value):
        return value
    if re.fullmatch(r"[A-Z][a-z]{2}, [0-9]{2} [A-Z][a-z]{2} [0-9]{4} "
                    r"[0-9]{2}:[0-9]{2}:[0-9]{2} GMT", value):
        try:
            date = parsedate_to_datetime(value)
            return value if format_datetime(date, usegmt=True) == value else None
        except (ValueError, TypeError, OverflowError):
            pass
    return None


def _log_openrouter_error(response, envelope=None):
    error = envelope.get("error") if isinstance(envelope, dict) else None
    error = error if isinstance(error, dict) else {}
    metadata = error.get("metadata")
    raw = metadata.get("raw") if isinstance(metadata, dict) else None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if len(raw) <= 8192 else None
        except (ValueError, RecursionError):
            raw = None
    upstream = raw.get("error", raw) if isinstance(raw, dict) else {}
    upstream = upstream if isinstance(upstream, dict) else {}
    diagnostic = {"http_status": response.status_code,
                  "error_code": _diagnostic_label(error.get("code")),
                  "error_type": _diagnostic_label(error.get("type")),
                  "error_message": _diagnostic_message(error.get("message")),
                  "provider_error_code": _diagnostic_label(upstream.get("code")),
                  "provider_error_type": _diagnostic_label(upstream.get("type")),
                  "provider_error_message": _diagnostic_message(upstream.get("message")),
                  "retry_after": _diagnostic_retry_after(response.headers.get("Retry-After"))}
    logger.warning("openrouter_error %s", json.dumps(diagnostic))


def _extract_json_from_text(text: str) -> dict:
    """
    Try to extract a JSON object from the model's raw text output.

    Qwen3 sometimes wraps JSON inside markdown code fences or includes
    a <think>…</think> reasoning block before the answer.  This function
    handles those cases gracefully.

    Steps:
        1. Strip any <think>…</think> block (Qwen3 "thinking" mode).
        2. Try direct json.loads on the whole remaining text.
        3. Look for a ```json … ``` fenced code block.
        4. Look for the first { … } substring.
        5. Give up and raise LLMResponseParseError.
    """
    # 1. Remove <think>…</think> blocks (Qwen3 thinking mode output)
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # 2. Direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 3. Fenced code block  ```json … ```
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 4. First { … } substring (greedy on closing brace)
    brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    # 5. Safe normalization: strip trailing commas before closing brackets/braces (e.g. [1, 2,] or {"a": 1,})
    cleaned_no_trailing = re.sub(r",\s*([\]}])", r"\1", cleaned)
    try:
        return json.loads(cleaned_no_trailing)
    except json.JSONDecodeError:
        pass

    if fence_match:
        try:
            return json.loads(re.sub(r",\s*([\]}])", r"\1", fence_match.group(1).strip()))
        except json.JSONDecodeError:
            pass

    if brace_match:
        try:
            return json.loads(re.sub(r",\s*([\]}])", r"\1", brace_match.group(0)))
        except json.JSONDecodeError:
            pass

    # 6. Nothing worked
    raise LLMResponseParseError(
        "Could not extract valid JSON from model response."
    )


def _validated_json(raw, schema):
    output = _extract_json_from_text(raw)
    if not isinstance(output, (dict, list)):
        raise LLMResponseParseError("Model response must contain a JSON object or array.")
    if schema is not None:
        try:
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(output)
        except (ValidationError, SchemaError):
            raise LLMResponseParseError("Model response did not satisfy the requested schema.") from None
    return output


def _envelope_usage(envelope, event):
    event["actual_model"] = llm_usage.safe_identifier(envelope.get("model"))
    if event["provider"] == "openrouter":
        event["actual_provider"] = llm_usage.safe_identifier(envelope.get("provider"))
        # A serving model change is observable; hidden failed attempts are not.
        if event["actual_model"] == event["requested_model"]:
            event["fallback_observed"] = False
        elif event["actual_model"] in settings.openrouter_models[1:]:
            event["fallback_observed"] = True
        usage = envelope.get("usage")
        if isinstance(usage, dict):
            event["input_tokens"] = llm_usage.number(usage.get("prompt_tokens"), integer=True)
            event["output_tokens"] = llm_usage.number(usage.get("completion_tokens"), integer=True)
            event["cost_usd"] = llm_usage.number(usage.get("cost"))
            if event["cost_usd"] is not None:
                event["cost_source"] = "provider_reported"
    else:
        event["input_tokens"] = llm_usage.number(envelope.get("prompt_eval_count"), integer=True)
        event["output_tokens"] = llm_usage.number(envelope.get("eval_count"), integer=True)
        event["internal_provider_attempts"] = 1
        event["fallback_observed"] = False


@timed("qwen.request")
async def generate_json_response(
    prompt: str,
    timeout: float | None = None,
    think: bool | None = None,
    num_predict: int | None = None,
    keep_alive: str | None = None,
    temperature: float | None = None,
    repeat_penalty: float | None = None,
    num_ctx: int | None = None,
    response_schema: dict | None = None,
) -> dict:
    """Preserve callers' JSON contract; one HTTP POST, no transport retry loop.

    Ollama-only controls (think, num_ctx, keep_alive, repeat_penalty) stay local.
    Cloud endpoints must support every transmitted parameter. Content repair
    remains in the existing bounded workflow, under a shared operation deadline.
    """
    cloud = settings.LLM_PROVIDER == "openrouter"
    model = settings.OPENROUTER_PRIMARY_MODEL.strip() if cloud else settings.OLLAMA_MODEL
    limit = num_predict if num_predict is not None else settings.OLLAMA_NUM_PREDICT
    request_timeout = settings.OPENROUTER_TIMEOUT_S if cloud else settings.OLLAMA_TIMEOUT
    if timeout is not None:
        request_timeout = min(request_timeout, timeout)
    effective_timeout = llm_usage.remaining_timeout(request_timeout)
    event = llm_usage.begin_attempt(settings.LLM_PROVIDER, model)
    started = time.perf_counter()
    try:
        headers = {}
        if cloud:
            key = settings.OPENROUTER_API_KEY.get_secret_value().strip()
            if not key:
                raise OpenRouterError("authentication")
            url = settings.OPENROUTER_BASE_URL + "/chat/completions"
            headers = {"Authorization": "Bearer " + key}
            payload = {"models": settings.openrouter_models, "stream": False,
                       "messages": [{"role": "user", "content": prompt}], "max_tokens": limit,
                       "response_format": {"type": "json_object"},
                       "provider": {"require_parameters": True, "data_collection": "deny",
                                    "zdr": settings.OPENROUTER_ZDR, "allow_fallbacks": True}}
            if response_schema is not None:
                payload["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": "interview_response", "strict": True, "schema": response_schema}}
            if temperature is not None:
                payload["temperature"] = temperature
        else:
            options = {"num_predict": limit}
            if temperature is not None:
                options["temperature"] = temperature
            if repeat_penalty is not None:
                options.update(repeat_penalty=repeat_penalty, repeat_last_n=64)
            if num_ctx is not None:
                options["num_ctx"] = num_ctx
            if current_engine() == "aws" and settings.AWS_OLLAMA_NUM_THREADS is not None:
                options["num_thread"] = settings.AWS_OLLAMA_NUM_THREADS
            origin = engine_origin(current_engine())
            if not origin:
                raise OllamaConnectionError("Selected inference engine is unavailable.")
            url = origin + "/api/generate"
            payload = {"model": model, "prompt": prompt, "stream": False,
                       "format": response_schema or "json",
                       "think": think if think is not None else settings.OLLAMA_THINK,
                       "keep_alive": keep_alive if keep_alive is not None else settings.OLLAMA_KEEP_ALIVE,
                       "options": options}
        with span("qwen.client_initialization"):
            client_options = {"trust_env": False} if not cloud and current_engine() == "aws" else {}
            if (not cloud and current_engine() == "local" and url.startswith("http://")
                    and not any(os.environ.get(key) for key in ("SSL_CERT_FILE", "SSL_CERT_DIR", "SSLKEYLOGFILE"))):
                client_options["verify"] = _default_verified_context()
            manager = httpx.AsyncClient(timeout=effective_timeout, follow_redirects=False, **client_options)
        # wait_for is a wall-clock bound, unlike httpx's per-phase inactivity timeouts.
        async def send():
            async with manager as client:
                with span("qwen.http_request"):
                    event["http_attempts"] = 1
                    return await client.post(url, json=payload, **({"headers": headers} if cloud else {}))
        response = await asyncio.wait_for(send(), effective_timeout)
        event["http_status"] = response.status_code
        # Preserve Ollama's status-based exceptions even for plain-text errors.
        if not cloud and response.status_code == 404:
            raise OllamaModelNotFoundError("Configured Ollama model was not found.")
        if not cloud and response.status_code != 200:
            raise LLMServiceError(f"Ollama returned HTTP {response.status_code}.")
        try:
            with span("qwen.envelope_parse"):
                envelope = response.json()
        except (ValueError, UnicodeError):
            if response.status_code != 200:
                if cloud:
                    _log_openrouter_error(response)
                    raise _cloud_error(response.status_code) from None
                raise LLMServiceError("Ollama returned an HTTP error.") from None
            raise LLMResponseParseError("Provider returned a non-JSON envelope.") from None
        if cloud and response.status_code != 200:
            # Error envelopes can echo user data even in model/provider fields.
            # Keep only validated numeric usage; diagnostic prose is allowlisted.
            if isinstance(envelope, dict):
                _envelope_usage({"usage": envelope.get("usage")}, event)
            _log_openrouter_error(response, envelope)
            raise _cloud_error(response.status_code)
        if isinstance(envelope, dict):
            _envelope_usage(envelope, event)
        if cloud:
            if not isinstance(envelope, dict):
                raise LLMResponseParseError("Provider returned an invalid envelope.")
            if "error" in envelope:
                error = envelope["error"]
                code = error.get("code") if isinstance(error, dict) else None
                raise _cloud_error(code)
            try:
                choice = envelope["choices"][0]
                if choice.get("finish_reason") in {"length", "content_filter", "error"}:
                    raise LLMResponseParseError("Provider did not return a complete answer.")
                raw = choice["message"]["content"]
            except (KeyError, IndexError, TypeError, AttributeError):
                raise LLMResponseParseError("Provider returned an invalid completion.") from None
        else:
            if not isinstance(envelope, dict):
                raise LLMResponseParseError("Ollama returned an invalid response envelope.")
            raw = envelope.get("response")
            metric("qwen.metrics", **{k: envelope[k] for k in ("prompt_eval_count", "eval_count")
                                      if isinstance(envelope.get(k), (int, float))},
                   **{k + "_ms": envelope[k] / 1e6 for k in ("load_duration", "prompt_eval_duration", "eval_duration", "total_duration")
                      if isinstance(envelope.get(k), (int, float))})
        if not isinstance(raw, str) or not raw.strip():
            raise LLMResponseParseError("Provider returned no completed answer.")
        with span("qwen.parse"):
            result = _validated_json(raw.strip(), response_schema)
        event["status"] = "success"
        return result
    except asyncio.CancelledError:
        deadline = llm_usage._deadline.get()
        event["status"] = "timeout" if deadline is not None and time.monotonic() >= deadline else "cancelled"
        raise
    except (httpx.TimeoutException, asyncio.TimeoutError):
        event["status"] = "timeout"
        error = LLMTimeoutError if cloud else OllamaTimeoutError
        raise error("Inference request timed out.") from None
    except httpx.RequestError:
        event["status"] = "connection_error"
        error = OpenRouterError("connection") if cloud else OllamaConnectionError("Cannot connect to Ollama.")
        raise error from None
    except OpenRouterError as exc:
        event["status"] = exc.kind
        raise
    except LLMResponseParseError:
        event["status"] = "invalid_response"
        raise
    finally:
        event["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        llm_usage.record(event)
