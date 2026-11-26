"""
Semantic Matching & Gap Analysis Endpoint — POST /api/v1/analysis/match.
"""

import time
from functools import partial

from anyio import CapacityLimiter, to_thread
from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError

from app.schemas.analysis import MatchAnalysisRequest, MatchAnalysisResponse
from app.services.semantic_matcher import calculate_match_analysis


router = APIRouter()
# Matching previously ran serially on the event loop. Keep one CPU batch in flight.
_match_limiter = CapacityLimiter(1)


@router.post(
    "/match",
    response_model=MatchAnalysisResponse,
    summary="Compute semantic skill matching and gap analysis between resume and JD",
    status_code=status.HTTP_200_OK,
)
async def match_resume_and_job(request: MatchAnalysisRequest) -> MatchAnalysisResponse:
    """
    Perform local semantic embedding comparison between candidate profile (Phase 4)
    and job profile (Phase 5) using Sentence Transformers ('all-MiniLM-L6-v2')
    and vector cosine similarity.

    Flow:
        1. Extract skills from CandidateProfile and JobProfile.
        2. Filter distinct technology guards (e.g. Java != JavaScript).
        3. Compute cosine similarity matrix via SentenceTransformers embeddings.
        4. Classify skills into matched and gaps against the configured threshold.
        5. Calculate weighted, deterministic match score (0-100).
        6. Return MatchAnalysisResponse with timing metadata.
    """
    start_time = time.perf_counter()

    try:
        match = partial(calculate_match_analysis,
            candidate_profile=request.candidate_profile,
            job_profile=request.job_profile,
            threshold=request.threshold,
        )
        response = await to_thread.run_sync(match, limiter=_match_limiter)
    except ValidationError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Schema validation error during match analysis: {str(err)}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during semantic matching analysis: {str(exc)}",
        )

    processing_time_ms = int((time.perf_counter() - start_time) * 1000)
    response.processing_time_ms = processing_time_ms

    return response
