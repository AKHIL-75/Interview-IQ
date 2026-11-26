"""
API v1 router.

Aggregates all v1 endpoint routers into a single router
that is mounted on the main application under the /api/v1 prefix.

New endpoint modules should be included here as the project grows.
"""

from fastapi import APIRouter, Depends
from app.core.auth import get_current_auth
from app.core.inference import request_engine

from app.api.v1.endpoints import health
from app.api.v1.endpoints import ai_test
from app.api.v1.endpoints import resume
from app.api.v1.endpoints import job
from app.api.v1.endpoints import analysis
from app.api.v1.endpoints import interview
from app.api.v1.endpoints import evaluation
from app.api.v1.endpoints import audio
from app.api.v1.endpoints import speech
from app.api.v1.endpoints import speech_stt


api_router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(get_current_auth)])

# Health check endpoints
api_router.include_router(health.router, tags=["Health"])

# Phase 3 — AI / LLM test endpoint
protected_router.include_router(ai_test.router, tags=["AI"], dependencies=[Depends(request_engine)])

# Phase 4 — Resume processing and parsing
protected_router.include_router(resume.router, prefix="/resume", tags=["Resume"], dependencies=[Depends(request_engine)])

# Phase 5 — Job description processing and skill extraction
protected_router.include_router(job.router, prefix="/job", tags=["Job"], dependencies=[Depends(request_engine)])

# Phase 6 — Semantic matching and gap analysis
protected_router.include_router(analysis.router, prefix="/analysis", tags=["Analysis"])

# Phase 7 — Personalized Question Generation
protected_router.include_router(interview.router, prefix="/interview", tags=["Interview"])

# Phase 10 — Answer Evaluation Engine
protected_router.include_router(evaluation.router, prefix="/evaluation", tags=["Evaluation"], dependencies=[Depends(request_engine)])

# Phase 15 — Audio Transcription (Azure Speech STT)
protected_router.include_router(audio.router, prefix="/audio", tags=["Audio"])
protected_router.include_router(speech.router, prefix="/speech", tags=["Speech"])
protected_router.include_router(speech_stt.router, prefix="/speech", tags=["Speech"])
api_router.include_router(protected_router)

