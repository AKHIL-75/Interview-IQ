"""Request-local, bounded inference accounting. Never stores prompts or user IDs."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import logging
import math
import re
import hashlib
import hmac
import secrets
import time
from uuid import uuid4

from app.core.config import settings

_operation = ContextVar("llm_operation", default="unspecified")
_attempt = ContextVar("llm_workflow_attempt", default=0)
_deadline = ContextVar("llm_deadline", default=None)
_collector = ContextVar("llm_collector", default=None)
_correlation = ContextVar("llm_correlation", default=None)
_process_salt = secrets.token_bytes(32)


def safe_identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_./: -]{1,128}", value) else None


def number(value, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return value if not integer or isinstance(value, int) else None


def record(event):
    collector = _collector.get()
    if collector is not None:
        if len(collector) >= 2048:
            raise RuntimeError("Inference capture limit exceeded")
        collector.append(event.copy())
    logging.getLogger("app.llm_usage").info("llm_attempt %s", json.dumps(event, allow_nan=False))


@contextmanager
def capture_usage():
    events = []
    token = _collector.set(events)
    try:
        yield events
    finally:
        _collector.reset(token)


def operation(name):
    """Bound the whole orchestration, including content repairs and child calls."""
    def decorate(fn):
        @wraps(fn)
        async def run(*args, **kwargs):
            from app.services.llm_service import LLMTimeoutError
            parent_deadline = _deadline.get()
            deadline = min(parent_deadline or float("inf"), time.monotonic() + settings.LLM_OPERATION_TIMEOUT_S)
            label = name(*args, **kwargs) if callable(name) else name
            tokens = (_operation.set(label), _attempt.set(0), _deadline.set(deadline))
            correlation = _correlation.get()
            if correlation is None:
                request = kwargs.get("request") if "request" in kwargs else (args[0] if args else None)
                correlation = {"operation_id": uuid4().hex}
                for key in ("session_id", "question_id"):
                    value = getattr(request, key, None)
                    if isinstance(value, str) and value:
                        # Process-local pseudonyms, log metadata only; never metric labels.
                        correlation[key.replace("_id", "_ref")] = hmac.new(
                            _process_salt, value.encode(), hashlib.sha256).hexdigest()[:16]
            correlation_token = _correlation.set(correlation)
            try:
                return await asyncio.wait_for(fn(*args, **kwargs), max(0, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                raise LLMTimeoutError("The LLM operation exceeded its time budget.") from None
            finally:
                _operation.reset(tokens[0]); _attempt.reset(tokens[1]); _deadline.reset(tokens[2])
                _correlation.reset(correlation_token)
        return run
    return decorate


def begin_attempt(provider, requested_model):
    attempt = _attempt.get()
    _attempt.set(attempt + 1)
    return {**(_correlation.get() or {}), "operation": _operation.get(), "provider": provider, "requested_model": requested_model,
            "actual_model": None, "actual_provider": None, "http_attempts": 0,
            "workflow_retry_index": attempt, "internal_provider_attempts": None,
            "fallback_observed": None, "status": "failed", "http_status": None,
            "input_tokens": None, "output_tokens": None, "cost_usd": None,
            "cost_source": "unavailable"}


def remaining_timeout(requested):
    deadline = _deadline.get()
    return min(requested, max(0.001, deadline - time.monotonic())) if deadline is not None else requested
