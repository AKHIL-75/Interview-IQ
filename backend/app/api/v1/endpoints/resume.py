"""
Resume processing endpoint — POST /api/v1/resume/parse.
"""
from app.services.llm_service import OpenRouterError, LLMTimeoutError
from app.services import llm_usage


import time
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.auth import AuthUser, get_optional_auth
from starlette.concurrency import run_in_threadpool
from app.core.config import settings
from app.core.inference import current_engine
from app.prompts.resume_prompts import build_resume_extraction_prompt
from app.schemas.resume import CandidateProfile, ResumeParseResponse
from app.services.performance import span
from app.services import llm_service
from app.services.persistence_service import persist_resume
from app.services.resume_parser import (
    MAX_FILE_SIZE_BYTES,
    CorruptedFileError,
    EmptyFileError,
    FileTooLargeError,
    NoExtractableTextError,
    ResumeParserError,
    UnsupportedFileTypeError,
    parse_resume_file,
)


router = APIRouter()


def _normalize_profile_keys(data: dict) -> dict:
    """
    Ensure common model output synonyms map gracefully to CandidateProfile schema keys.
    """
    normalized = dict(data)

    # Name mapping
    if "candidate_name" not in normalized or not normalized["candidate_name"]:
        for alias in ("name", "full_name", "candidate"):
            if alias in normalized and normalized[alias]:
                normalized["candidate_name"] = normalized[alias]
                break

    # Skills mapping
    if "extracted_skills" not in normalized or not normalized["extracted_skills"]:
        for alias in ("skills", "technical_skills", "tech_stack"):
            if alias in normalized and isinstance(normalized[alias], (list, str)):
                normalized["extracted_skills"] = normalized[alias]
                break

    # Experience mapping
    if "experience_years" not in normalized or normalized["experience_years"] is None:
        for alias in ("years_of_experience", "experience", "total_experience_years"):
            if alias in normalized and normalized[alias] is not None:
                normalized["experience_years"] = normalized[alias]
                break

    # Projects mapping
    if "key_projects" not in normalized or not normalized["key_projects"]:
        for alias in ("projects", "academic_projects", "major_projects"):
            if alias in normalized and isinstance(normalized[alias], list):
                normalized["key_projects"] = normalized[alias]
                break

    # Project items internal key mapping
    if "key_projects" in normalized and isinstance(normalized["key_projects"], list):
        cleaned_projects = []
        for proj in normalized["key_projects"]:
            if isinstance(proj, dict):
                p = dict(proj)
                if "name" not in p or not p["name"]:
                    for alias in ("title", "project_name", "projectName"):
                        if alias in p:
                            p["name"] = p[alias]
                            break
                if "technologies" not in p or not p["technologies"]:
                    for alias in ("tech", "tools", "tech_stack", "stack"):
                        if alias in p:
                            p["technologies"] = p[alias]
                            break
                if "description" not in p:
                    for alias in ("details", "summary", "overview"):
                        if alias in p:
                            p["description"] = p[alias]
                            break
                cleaned_projects.append(p)
            elif isinstance(proj, str):
                cleaned_projects.append({"name": proj, "description": "", "technologies": []})
        normalized["key_projects"] = cleaned_projects

    return normalized


@router.post(
    "/parse",
    response_model=ResumeParseResponse,
    summary="Upload and parse resume into structured candidate profile",
    status_code=status.HTTP_200_OK,
)
@llm_usage.operation("resume_parse")
async def parse_resume(
    file: UploadFile = File(...),
    auth: Optional[AuthUser] = Depends(get_optional_auth),
) -> ResumeParseResponse:
    """
    Parse an uploaded PDF or DOCX resume and extract a structured CandidateProfile
    using local Qwen3 inference via Ollama.

    Flow:
        1. Validate filename, file extension, and upload size.
        2. Read binary file contents and verify signature.
        3. Extract text from PDF/DOCX pages or paragraphs/tables.
        4. Dispatch text to Qwen3 using structured prompt (think=False).
        5. Validate structured candidate profile via Pydantic.
        6. Return ResumeParseResponse with timing and metadata.
    """
    start_time = time.perf_counter()

    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No resume file was provided in the upload request.",
        )

    # 1. Read binary content
    try:
        content = await file.read(MAX_FILE_SIZE_BYTES + 1)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded file: {str(exc)}",
        )

    # 2. Extract and normalize text
    try:
        with span("resume.extract_text"):
            extracted_text, file_type = await run_in_threadpool(parse_resume_file, file.filename, content)
    except UnsupportedFileTypeError as err:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(err),
        )
    except FileTooLargeError as err:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(err),
        )
    except EmptyFileError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )
    except CorruptedFileError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )
    except NoExtractableTextError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(err),
        )
    except ResumeParserError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during resume document parsing: {str(exc)}",
        )

    raw_text_length = len(extracted_text)

    # 3. Build extraction prompt
    prompt = build_resume_extraction_prompt(extracted_text)
    response_schema = None
    if settings.LLM_PROVIDER == "ollama":
        response_schema = CandidateProfile.model_json_schema()
        response_schema["required"] = list(response_schema["properties"])
        response_schema["additionalProperties"] = False

    import logging
    logger = logging.getLogger(__name__)

    # Use the configured AWS runner context while allowing the local runner to reuse its own context.
    num_ctx = settings.AWS_OLLAMA_RESUME_NUM_CTX if current_engine() == "aws" else None
    try:
        try:
            logger.info(
                "[Resume Debug] requested_model=%s num_predict=700 num_ctx=%s resume_chars=%d prompt_chars=%d attempt=1",
                settings.OLLAMA_MODEL if settings.LLM_PROVIDER == "ollama" else settings.OPENROUTER_PRIMARY_MODEL,
                num_ctx,
                raw_text_length,
                len(prompt),
            )
            llm_output = await llm_service.generate_json_response(
                prompt=prompt,
                response_schema=response_schema,
                think=False,
                num_predict=700,
                temperature=0.2,
                repeat_penalty=1.1,
                num_ctx=num_ctx,
            )
        except (llm_service.LLMResponseParseError, llm_service.LLMServiceError) as first_err:
            # Do not retry if server is offline, model is not found, or timed out
            if isinstance(first_err, (llm_service.OllamaConnectionError, llm_service.OllamaModelNotFoundError, llm_service.LLMTimeoutError, llm_service.OpenRouterError)):
                raise
            logger.warning(
                "[Resume] Extraction failed; retrying once with adjusted repetition penalty.",
            )
            logger.info(
                "[Resume Debug] requested_model=%s num_predict=700 num_ctx=%s resume_chars=%d prompt_chars=%d attempt=2",
                settings.OLLAMA_MODEL if settings.LLM_PROVIDER == "ollama" else settings.OPENROUTER_PRIMARY_MODEL,
                num_ctx,
                raw_text_length,
                len(prompt),
            )
            # MAXIMUM ONE controlled retry with higher entropy and repetition penalty
            llm_output = await llm_service.generate_json_response(
                prompt=prompt,
                response_schema=response_schema,
                think=False,
                num_predict=700,
                temperature=0.3,
                repeat_penalty=1.15,
                num_ctx=num_ctx,
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
            detail=f"Ollama returned unparseable JSON during resume extraction: {str(err)}",
        )
    except llm_service.LLMServiceError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ollama inference error: {str(err)}",
        )

    # 5. Pydantic validation & schema sanitization
    try:
        normalized_data = _normalize_profile_keys(llm_output)
        candidate_profile = CandidateProfile(**normalized_data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to validate candidate profile schema from LLM output: {str(exc)}",
        )

    processing_time_ms = int((time.perf_counter() - start_time) * 1000)

    # 6. Persist to Supabase if authenticated
    persisted_resume_id = None
    if auth:
        import logging
        logger = logging.getLogger(__name__)
        logger.info("[Resume] Authenticated persistence started")
        try:
            record = await persist_resume(
                token=auth.token,
                user_id=auth.user_id,
                file_name=file.filename or "resume",
                candidate_profile=candidate_profile.model_dump(),
                raw_text=extracted_text[:4000] if extracted_text else None,
            )
            if record and record.get("id"):
                persisted_resume_id = record.get("id")
                logger.info("[Resume] Persistence succeeded")
            else:
                logger.error("[Resume] insert succeeded: NO | returned row ID: null")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Resume persistence failed: Supabase PostgREST insert did not return a valid record.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("[Resume] Persistence failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Resume persistence exception: {str(exc)}",
            )
    else:
        import logging
        logging.getLogger(__name__).info(
            "[Resume] persistence function entered: NO | authenticated user: NO (anonymous upload)"
        )

    return ResumeParseResponse(
        success=True,
        filename=file.filename,
        file_type=file_type,
        raw_text_length=raw_text_length,
        candidate_profile=candidate_profile,
        processing_time_ms=processing_time_ms,
        resume_id=persisted_resume_id,
    )


