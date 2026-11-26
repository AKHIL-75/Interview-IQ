"""
Job Description Processing Endpoint — POST /api/v1/job/parse.
"""
from app.services.llm_service import OpenRouterError, LLMTimeoutError


import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from app.core.auth import AuthUser, get_optional_auth
from app.schemas.job import JobParseRequest, JobParseResponse
from app.services import llm_service
from app.services.jd_parser import (
    EmptyJDError,
    JDTooLargeError,
    JDTooShortError,
    parse_job_description,
)
from app.services.persistence_service import persist_job_description


router = APIRouter()


@router.post(
    "/parse",
    response_model=JobParseResponse,
    summary="Parse raw job description text into structured JobProfile",
    status_code=status.HTTP_200_OK,
)
async def parse_job(
    request: JobParseRequest,
    auth: Optional[AuthUser] = Depends(get_optional_auth),
) -> JobParseResponse:
    """
    Parse a raw job description and extract a structured JobProfile
    using local Qwen3 inference via Ollama.

    Flow:
        1. Validate request body (non-empty, length thresholds).
        2. Normalize text spacing and control characters.
        3. Dispatch text to Qwen3 using structured prompt (think=False).
        4. Validate extracted role, required skills, preferred skills, and experience via Pydantic.
        5. Return JobParseResponse with timing and metadata.
    """
    start_time = time.perf_counter()

    try:
        job_profile, normalized_text = await parse_job_description(request.text)
    except EmptyJDError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )
    except JDTooShortError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(err),
        )
    except JDTooLargeError as err:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(err),
        )
    except OpenRouterError as err:
        raise HTTPException(err.status_code, "The inference provider could not complete the request.") from None
    except llm_service.OllamaConnectionError as err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(err),
        )
    except llm_service.OllamaModelNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(err),
        )
    except LLMTimeoutError as err:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(err),
        )
    except llm_service.LLMResponseParseError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ollama returned unparseable JSON during job description extraction: {str(err)}",
        )
    except ValidationError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to validate job profile schema from LLM output: {str(err)}",
        )
    except llm_service.LLMServiceError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ollama inference error: {str(err)}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during job description parsing: {str(exc)}",
        )

    processing_time_ms = int((time.perf_counter() - start_time) * 1000)

    # Persist to Supabase if authenticated
    persisted_jd_id = None
    if auth:
        import logging
        logger = logging.getLogger(__name__)
        logger.info('parse_job: [Job] persistence function entered')
        try:
            record = await persist_job_description(
                token=auth.token,
                user_id=auth.user_id,
                title=job_profile.role_title or "Software Engineer",
                raw_text=request.text,
                job_profile=job_profile.model_dump(),
            )
            if record and record.get("id"):
                persisted_jd_id = record.get("id")
                logger.info('parse_job: [Job] insert succeeded')
            else:
                logger.error("[Job] insert succeeded: NO | returned row ID: null")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Job description persistence failed: Supabase PostgREST insert did not return a valid record.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error('parse_job: [Job] Persistence exception for user')
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Job description persistence exception: {str(exc)}",
            )
    else:
        import logging
        logging.getLogger(__name__).info(
            "[Job] persistence function entered: NO | authenticated user: NO (anonymous upload)"
        )

    return JobParseResponse(
        success=True,
        raw_text_length=len(request.text),
        job_profile=job_profile,
        processing_time_ms=processing_time_ms,
        job_description_id=persisted_jd_id,
    )

