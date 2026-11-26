"""
Interview-IQ Backend — FastAPI Application Entry Point.

This module creates the FastAPI application instance, configures
CORS middleware for the React frontend, and includes the versioned
API router.

Run with:
    uvicorn app.main:app --reload --port 8000 --no-proxy-headers
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.inference import ENGINE_HEADER, EngineAvailability
from app.api.v1.api import api_router
from app.services.performance import trace
from app.services.llm_service import preload_local_ollama
from app.core.exceptions import install_exception_handlers, handle_unexpected_error
from app.core.request_limits import RequestLimitsMiddleware
import json
import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import time
from uuid import uuid4


@asynccontextmanager
async def lifespan(application: FastAPI):
    logger = logging.getLogger("app.api")
    logger.info(f"[Config] Supabase URL configured: {'YES' if bool(settings.SUPABASE_URL) else 'NO'}")
    logger.info(f"[Config] Supabase anon key configured: {'YES' if bool(settings.SUPABASE_ANON_KEY) else 'NO'}")

    task = None
    if settings.OLLAMA_PREWARM_ENABLED and settings.LLM_PROVIDER == "ollama":
        task = asyncio.create_task(preload_local_ollama())
        application.state.local_prewarm = task
    try:
        yield
    finally:
        if task is not None:
            application.state.local_prewarm = None
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


# Create the FastAPI application
# Interview-IQ Backend Service
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered personalized mock interview platform backend.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
install_exception_handlers(app)
app.state.engine_availability = EngineAvailability()

# ---------------------------------------------------------------------------
# CORS Configuration
# ---------------------------------------------------------------------------
# Allow the configured frontend origin and optional development aliases.
# Compose supplies its exact Nginx origin and clears development aliases.
# ---------------------------------------------------------------------------


@app.middleware("http")
async def log_requests(request, call_next):
    import logging
    logger = logging.getLogger("app.api")
    measured = settings.PERFORMANCE_DIAGNOSTICS and request.method == "POST" and request.url.path in {
        "/api/v1/resume/parse", "/api/v1/job/parse", "/api/v1/analysis/match",
        "/api/v1/interview/generate-questions", "/api/v1/speech/synthesize",
        "/api/v1/audio/transcribe", "/api/v1/evaluation/evaluate", "/api/v1/interview/next-question", "/api/v1/interview/start", "/api/v1/interview/report"
    }
    timing = {"request_id": uuid4().hex, "route": request.url.path, "start": time.perf_counter(), "stages": []} if measured else None
    context_token = trace.set(timing)
    try:
        try:
            response = await call_next(request)
        except Exception as exc:
            response = await handle_unexpected_error(request, exc)
        logger.info("http_response status=%s", response.status_code)
        if timing is not None:
            timing["status"] = response.status_code
            duration = round((time.perf_counter() - timing["start"]) * 1000, 2)
            response.headers["Server-Timing"] = f'app;dur={duration}'
            response.headers["X-Request-Id"] = timing["request_id"]
        return response
    finally:
        trace.reset(context_token)
        if timing is not None:
            duration = round((time.perf_counter() - timing.pop("start")) * 1000, 2)
            logging.getLogger("app.performance").warning(json.dumps({**timing, "duration_ms": duration}))

app.add_middleware(RequestLimitsMiddleware, api_prefix=settings.API_V1_PREFIX,
                   serial_inference=settings.INFERENCE_SERIAL_ADMISSION)
# Outermost: errors and rate-limit responses must also be readable by the UI.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", ENGINE_HEADER],
    expose_headers=["Server-Timing", "X-Request-Id", "Retry-After"],
)


# ---------------------------------------------------------------------------
# Include API Routers
# ---------------------------------------------------------------------------
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# ---------------------------------------------------------------------------
# Root Endpoint
# ---------------------------------------------------------------------------
@app.get(
    "/",
    summary="Root",
    description="Root endpoint confirming the Interview-IQ backend is running.",
)
def root():
    """Root endpoint — confirms the server is running."""
    return {
        "message": f"{settings.APP_NAME} is running.",
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }
