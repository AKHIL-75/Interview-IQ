"""Server-owned Ollama destinations and request-scoped selection."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import ipaddress
import json
import re
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
import httpx

from app.core.config import settings
from app.core.request_limits import LocalRateLimiter


ENGINE_HEADER = "X-Inference-Engine"
REVIEWER_GPU_HEADER = "X-Interview-IQ-Reviewer-GPU"
ENGINES = ("local", "aws")
_PRIVATE_NETWORKS = tuple(map(ipaddress.ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")))
_selection = ContextVar("inference_engine", default=None)
_reviewer_gpu_allowed = ContextVar("reviewer_gpu_allowed", default=False)
_reviewer_gpu_admitted = ContextVar("reviewer_gpu_admitted", default=False)
_reviewer_gpu_limit = LocalRateLimiter(limit=6)


def current_engine():
    return _selection.get() or settings.DEFAULT_INFERENCE_ENGINE


def switching_enabled():
    return settings.LLM_PROVIDER == "ollama" and settings.OLLAMA_MODEL == "qwen3:4b"


def can_use_local_gpu(request: Request) -> bool:
    return not settings.STAGING_GPU_REVIEWER_ONLY or request.headers.getlist(REVIEWER_GPU_HEADER) == ["1"]


def _admit_local_gpu():
    if not settings.STAGING_GPU_REVIEWER_ONLY or _reviewer_gpu_admitted.get():
        return
    if not _reviewer_gpu_allowed.get():
        raise HTTPException(403, "Local GPU is restricted to the approved reviewer network.")
    retry = _reviewer_gpu_limit.retry_after("staging-laptop")
    if retry:
        raise HTTPException(429, "Local GPU request limit reached.", headers={"Retry-After": str(retry)})
    _reviewer_gpu_admitted.set(True)


def engine_origin(engine):
    if engine == "local":
        return settings.OLLAMA_BASE_URL.rstrip("/")
    if engine != "aws":
        return None
    # Only the operator can configure this origin. Private DNS is controlled
    # by the operator's network. Permit loopback for private tunnels.
    value = settings.AWS_OLLAMA_BASE_URL.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (not host or parsed.scheme not in {"http", "https"} or parsed.username is not None
                or parsed.path or parsed.query or parsed.fragment or parsed.port == 0
                or not re.fullmatch(r"[A-Za-z0-9.:\[\]-]+", parsed.netloc)):
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*", host):
                return None
        else:
            if not (address.is_loopback or any(address in block for block in _PRIVATE_NETWORKS)):
                return None
    except ValueError:
        return None
    return value


@contextmanager
def _use_engine(engine):
    token = _selection.set(engine)
    try:
        yield
    finally:
        _selection.reset(token)


async def request_engine(request: Request):
    values = request.headers.getlist(ENGINE_HEADER)
    if values and (len(values) != 1 or values[0] not in ENGINES):
        raise HTTPException(422, "Unknown inference engine.")
    engine = values[0] if values else None
    if engine and not switching_enabled():
        raise HTTPException(503, "Requested inference engine unavailable.")
    if engine == "aws" and not engine_origin(engine):
        raise HTTPException(503, "AWS inference is not configured.")
    reviewer = _reviewer_gpu_allowed.set(can_use_local_gpu(request))
    admitted = _reviewer_gpu_admitted.set(False)
    try:
        if (engine or settings.DEFAULT_INFERENCE_ENGINE) == "local":
            _admit_local_gpu()
        with _use_engine(engine):
            yield
    finally:
        _reviewer_gpu_admitted.reset(admitted)
        _reviewer_gpu_allowed.reset(reviewer)


def session_engine(row):
    config = row.get("interview_config")
    if config is not None and not isinstance(config, dict):
        raise HTTPException(409, "Invalid saved interview configuration.")
    saved = (config or {}).get("inference_engine", "local")
    if saved not in ENGINES or _selection.get() not in (None, saved):
        raise HTTPException(409, "The saved inference engine is fixed for this session.")
    if config and "inference_engine" in config and not switching_enabled():
        raise HTTPException(503, "Saved inference engine unavailable.")
    if saved == "local":
        _admit_local_gpu()
    return _use_engine(saved)


async def require_start_engine(request: Request):
    if ENGINE_HEADER in request.headers:
        status = await request.app.state.engine_availability.read()
        if not status[current_engine()]:
            raise HTTPException(503, "Selected inference engine unavailable.")


async def _has_model(engine):
    origin = engine_origin(engine)
    if not origin or not switching_enabled():
        return False

    async def probe():
        async with httpx.AsyncClient(timeout=2, follow_redirects=False, trust_env=engine == "local") as client:
            async with client.stream("GET", origin + "/api/tags") as response:
                if response.status_code != 200:
                    return False
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16_384):
                    if len(data) + len(chunk) > 1_048_576:
                        return False
                    data.extend(chunk)
            envelope = json.loads(data)
            models = envelope.get("models") if isinstance(envelope, dict) else None
            return isinstance(models, list) and any(
                isinstance(model, dict) and model.get("name") == settings.OLLAMA_MODEL for model in models
            )

    try:
        return await asyncio.wait_for(probe(), timeout=3)
    except (httpx.HTTPError, httpx.InvalidURL, asyncio.TimeoutError, ValueError, RecursionError):
        return False


class EngineAvailability:
    """One short, shared probe interval per worker, independent of user choice."""

    def __init__(self):
        self.lock = asyncio.Lock()
        self.expires = 0
        self.status = {}

    async def read(self):
        async with self.lock:
            if time.monotonic() >= self.expires:
                results = await asyncio.gather(*(_has_model(engine) for engine in ENGINES))
                self.status = dict(zip(ENGINES, results))
                self.expires = time.monotonic() + 5
            return self.status
