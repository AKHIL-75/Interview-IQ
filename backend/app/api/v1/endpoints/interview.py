"""
Interview Endpoints — Phase 7: Personalized Question Generation.

POST /api/v1/interview/generate-questions
"""
from app.services.llm_service import OpenRouterError, LLMTimeoutError
from app.services.performance import timed


import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError, TypeAdapter
from app.schemas.request import Identifier

from app.core.auth import AuthUser, get_current_auth, get_optional_auth
from app.core.inference import current_engine, request_engine, require_start_engine, switching_enabled
from app.schemas.adaptive import (
    AdaptiveNextQuestionRequest,
    AdaptiveNextQuestionResponse,
    InterviewStartRequest,
    InterviewStartResponse,
)
from app.schemas.interview import (
    QuestionGenerationRequest,
    QuestionGenerationResponse,
)
from app.services.adaptive_interviewer import (
    InterviewStateError,
    process_adaptive_next_question,
    process_adaptive_start,
)
from app.services.llm_service import (
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
    LLMResponseParseError,
    LLMServiceError,
)
from app.services.persistence_service import (
    read_owned_rows,
    get_user_interview_reports,
    get_user_interview_sessions,
    get_interview_report_by_id,
    get_user_dashboard_analytics,
    persist_candidate_answer,
    persist_interview_question,
    persist_interview_report,
    persist_interview_session,
    update_interview_session,
)
from app.services.interview_commit import commit_answer, session_lock
from app.schemas.evaluation import CONCEPTUAL_RUBRIC, saved_answer_rubric
from app.services.question_generator import generate_interview_questions
from app.services.report_generator import (
    calculate_grade,
    generate_final_report,
    normalize_report_for_response,
    analyze_topic_performance,
    build_adaptive_summary,
)



router = APIRouter()


@router.post(
    "/start",
    dependencies=[Depends(get_current_auth), Depends(request_engine), Depends(require_start_engine)],
    response_model=InterviewStartResponse,
    summary="Initialize adaptive interview session, plan, and first question",
    status_code=status.HTTP_200_OK,
)
async def start_interview(
    request: InterviewStartRequest,
    auth: AuthUser = Depends(get_current_auth),
) -> InterviewStartResponse:
    """
    Initializes a realistic mock interview session:
    - Creates structured interview plan
    - Determines stage progression (Static 5/10/15/20 or Dynamic)
    - Returns one scoped technical question, or a general opening introduction.
    - Persists session and Question 1 to Supabase if authenticated.
    """
    try:
        # Foreign keys must belong to the caller before creating a session.
        for table, record_id in (("resumes", request.resume_id), ("job_descriptions", request.job_description_id)):
            if record_id and not await read_owned_rows(auth.token, table, {"id": record_id, "user_id": str(auth.user_id)}):
                raise HTTPException(404, "Resume or job description not found.")
        response = await process_adaptive_start(request)

        # Persist session and Question 1 to Supabase if authenticated
        if auth:
            session_rec = await persist_interview_session(
                token=auth.token,
                user_id=auth.user_id,
                session_id=response.session_id,
                role=request.role or "Software Engineer",
                interview_type=request.interview_type or "Technical",
                difficulty=request.difficulty or "Medium",
                interview_mode=request.interview_mode or "STATIC",
                question_count=request.question_count or 10,
                interview_config={
                    **({"inference_engine": current_engine()} if switching_enabled() else {}),
                    "rubric_version": CONCEPTUAL_RUBRIC,
                    "role": request.role,
                    "interview_type": request.interview_type,
                    "difficulty": request.difficulty,
                    "interview_mode": request.interview_mode,
                    "question_count": request.question_count,
                    "mode": request.mode,
                    "subject": request.subject,
                },
                interview_plan=response.interview_plan,
                interview_state=response.interview_state,
                analysis=request.analysis,
                resume_id=request.resume_id,
                job_description_id=request.job_description_id,
            )

            if not session_rec:
                raise HTTPException(503, "Interview session could not be saved. Please retry.")
            if response.first_question:
                session_db_uuid = session_rec.get("id") if session_rec else None
                first_saved = await persist_interview_question(
                    token=auth.token,
                    session_id_str=response.session_id,
                    question=response.first_question.model_dump(),
                    question_order=1,
                    session_db_uuid=session_db_uuid,
                )

                if not first_saved:
                    raise HTTPException(503, "Opening question could not be saved. Please retry.")

        return response
    except OpenRouterError as err:
        raise HTTPException(err.status_code, "The inference provider could not complete the request.") from None
    except (OllamaConnectionError, OllamaModelNotFoundError):
        raise HTTPException(503, "Question generation is unavailable. Please retry.") from None
    except LLMTimeoutError:
        raise HTTPException(504, "Question generation timed out. Please retry.") from None
    except LLMResponseParseError:
        raise HTTPException(502, "A valid subject question could not be generated. Please retry.") from None
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initialize interview: {str(exc)}",
        )



@router.post(
    "/generate-questions",
    dependencies=[Depends(request_engine)],
    response_model=QuestionGenerationResponse,
    summary="Generate personalized interview questions using Qwen3 via Ollama",
    status_code=status.HTTP_200_OK,
)
async def generate_questions(
    request: QuestionGenerationRequest,
) -> QuestionGenerationResponse:
    """
    Generate tailored interview questions based on:
    - Candidate resume profile (skills, projects, experience)
    - Job description requirements and seniority
    - Semantic match & gap analysis (matched competencies, missing skills)
    - Selected interview type (Technical / HR / Mixed)
    - Selected difficulty (Easy / Medium / Hard)
    - Desired question count (1 to 15)
    """
    try:
        response = await generate_interview_questions(request)
        return response
    except OpenRouterError as err:
        raise HTTPException(err.status_code, "The inference provider could not complete the request.") from None
    except OllamaConnectionError as err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Ollama is offline or unreachable: {str(err)}",
        )
    except LLMTimeoutError as err:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Ollama timed out while generating questions: {str(err)}",
        )
    except OllamaModelNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Requested model not found in Ollama: {str(err)}",
        )
    except LLMResponseParseError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ollama returned unparseable output: {str(err)}",
        )
    except ValidationError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Validation error during question generation: {str(err)}",
        )
    except LLMServiceError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LLM service error: {str(err)}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during question generation: {str(exc)}",
        )


@router.post(
    "/next-question",
    dependencies=[Depends(request_engine)],
    response_model=AdaptiveNextQuestionResponse,
    summary="Adaptive interview decision engine & dynamic follow-up generation",
    status_code=status.HTTP_200_OK,
)
async def next_question(
    request: AdaptiveNextQuestionRequest,
    auth: AuthUser = Depends(get_current_auth),
) -> AdaptiveNextQuestionResponse:
    """
    Consumes candidate answer and Phase 10 evaluation results to deterministically decide
    next action (TARGETED_FOLLOW_UP, DEEPER_CHALLENGE, NEXT_TOPIC, or ADVANCE_DIFFICULTY)
    and dynamically generates follow-up or challenge question via local Qwen3.
    Persists candidate answer, evaluation, and newly generated question to Supabase if authenticated.
    """
    try:
        return await commit_answer(request, auth)
    except HTTPException:
        raise
    except InterviewStateError:
        logging.getLogger(__name__).warning("next_question_failed reason=saved_state")
        raise HTTPException(409, "Saved interview progress needs to be restored.") from None
    except OpenRouterError as err:
        raise HTTPException(err.status_code, "The inference provider could not complete the request.") from None
    except (OllamaConnectionError, OllamaModelNotFoundError) as err:
        logging.getLogger(__name__).warning("next_question_failed exception_type=%s", type(err).__name__)
        raise HTTPException(503, "Question generation is unavailable. Retry your saved answer.") from None
    except LLMTimeoutError:
        logging.getLogger(__name__).warning("next_question_failed reason=provider_timeout")
        raise HTTPException(504, "Question generation timed out. Retry your saved answer.") from None
    except LLMResponseParseError:
        logging.getLogger(__name__).warning("next_question_failed reason=invalid_model_output")
        raise HTTPException(502, "A valid next question could not be generated. Retry your saved answer.") from None
    except Exception as exc:
        # Log stack locations without exception text, prompts, answers or tokens.
        import traceback
        logging.getLogger(__name__).error("next_question_failed exception_type=%s stack=%s",
            type(exc).__name__, [(frame.name, frame.lineno) for frame in traceback.extract_tb(exc.__traceback__)])
        raise HTTPException(500, "Question progression failed. Retry your saved answer.") from None



@router.post(
    "/report",
    summary="Persist completed interview report to Supabase and mark session completed",
    status_code=status.HTTP_200_OK,
)
async def save_interview_report(
    report_data: Dict[str, Any],
    auth: AuthUser = Depends(get_current_auth),
):
    """
    POST /api/v1/interview/report
    Persists final performance report to public.interview_reports
    and marks public.interview_sessions as 'completed'.
    """
    session_id = report_data.get("sessionId") or report_data.get("session_id")
    try:
        TypeAdapter(Identifier).validate_python(session_id)
        duration = report_data.get("duration_secs", 0)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 <= duration <= 604800:
            raise ValueError()
    except (ValidationError, ValueError):
        raise HTTPException(422, "A valid session ID and duration are required.") from None
    async with session_lock((str(auth.user_id), session_id)):
        return await _save_owned_report(report_data, auth)


@timed("report.generate_save")
async def _save_owned_report(report_data, auth):
    session_id = report_data.get("sessionId") or report_data.get("session_id")
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session ID is required to persist report.",
        )

    sessions = await read_owned_rows(auth.token, "interview_sessions", {"session_id": session_id})
    if not sessions:
        raise HTTPException(404, "Interview session not found.")
    owned = sessions[0]
    if owned.get("status") == "completed":
        reports = await read_owned_rows(auth.token, "interview_reports", {"session_id": owned["id"]})
        if reports:
            return {"success": True, "session_id": session_id, "persisted": True,
                    "report": normalize_report_for_response(reports[0])}
    stored_questions = await read_owned_rows(auth.token, "interview_questions", {"session_id": owned["id"]})
    stored_answers = await read_owned_rows(auth.token, "candidate_answers", {"session_id": owned["id"]})
    stored_questions.sort(key=lambda q: q.get("question_order", 0))
    question_map = {q["id"]: q for q in stored_questions}
    questions = [{**q, "id": q["question_id"], "question": q["question_text"]} for q in stored_questions]
    stored_answers.sort(key=lambda a: question_map.get(a["question_id"], {}).get("question_order", 0))
    config = owned.get("interview_config") or {}
    answers = []
    for answer in stored_answers:
        question = question_map.get(answer["question_id"])
        if question:
            question_id = question["question_id"]
            evaluation = {**answer, "rubric_version": saved_answer_rubric(config, question_id)}
            answers.append({**answer, "questionId": question_id, "evaluation": evaluation})
    report_data = generate_final_report(
        session_id=session_id, role=owned["role"], interview_type=owned["interview_type"],
        difficulty=owned["difficulty"], questions=questions, answers=answers,
        duration_secs=report_data.get("duration_secs", 0),
        interview_plan=owned.get("interview_plan"), interview_state=owned.get("interview_state"),
        total_planned_questions=owned.get("question_count"),
        rubric_version=config.get("rubric_version"),
    )

    persisted = None
    if auth:
        persisted = await persist_interview_report(
            token=auth.token,
            user_id=auth.user_id,
            session_id_str=session_id,
            report_data=report_data,
        )

    if not persisted:
        raise HTTPException(503, "Report could not be saved. Retry to finish the interview.")
    normalized_report = normalize_report_for_response(persisted)

    return {
        "success": True,
        "session_id": session_id,
        "persisted": bool(persisted),
        "report": normalized_report,
    }


@router.post(
    "/generate-report",
    summary="Generate deterministic final performance report from interview questions and answers",
    status_code=status.HTTP_200_OK,
)
async def generate_report_endpoint(
    payload: Dict[str, Any],
    auth: Optional[AuthUser] = Depends(get_optional_auth),
):
    """
    POST /api/v1/interview/generate-report
    Generates a full, authoritative, viva-ready performance report payload
    without requiring immediate persistence.
    """
    session_id = payload.get("session_id") or payload.get("sessionId") or "session-preview"
    report = generate_final_report(
        session_id=session_id,
        role=payload.get("role") or "Software Engineer",
        interview_type=payload.get("interview_type") or payload.get("interviewType") or "Technical",
        difficulty=payload.get("difficulty") or "Medium",
        questions=payload.get("questions") or [],
        answers=payload.get("answers") or [],
        duration_secs=payload.get("duration_secs") or payload.get("durationSecs") or 0,
        interview_plan=payload.get("interview_plan"),
        interview_state=payload.get("interview_state"),
        total_planned_questions=payload.get("total_questions") or payload.get("totalQuestions"),
    )
    return {
        "success": True,
        "report": normalize_report_for_response(report),
    }


@router.get(
    "/history",
    summary="Retrieve user interview history and reports from Supabase",
    status_code=status.HTTP_200_OK,
)
async def get_interview_history(
    auth: AuthUser = Depends(get_current_auth),
):
    """
    GET /api/v1/interview/history
    Fetches user's historical interview sessions and reports protected by Supabase RLS.
    Returns both unified history sessions and backward-compatible reports collection.
    """
    sessions = await get_user_interview_sessions(
        token=auth.token,
        user_id=auth.user_id,
    )
    reports = await get_user_interview_reports(
        token=auth.token,
        user_id=auth.user_id,
    )
    return {
        "success": True,
        "count": len(sessions) if sessions else len(reports),
        "history": sessions,
        "reports": reports,
    }


@router.get(
    "/analytics",
    summary="Retrieve user dashboard analytics computed from real database data",
    status_code=status.HTTP_200_OK,
)
async def get_dashboard_analytics(
    auth: AuthUser = Depends(get_current_auth),
):
    """
    GET /api/v1/interview/analytics
    Calculates live dashboard analytics (total, completed, average score,
    performance dimensions, strengths, improvements, score trend)
    strictly from the authenticated user's records under Supabase RLS.
    """
    analytics = await get_user_dashboard_analytics(
        token=auth.token,
        user_id=auth.user_id,
    )
    return {
        "success": True,
        "analytics": analytics,
    }


@router.get(
    "/report/{report_id_or_session_id}",
    summary="Retrieve a specific historical interview report",
    status_code=status.HTTP_200_OK,
)
async def get_single_report(
    report_id_or_session_id: Identifier,
    auth: AuthUser = Depends(get_current_auth),
):
    """
    GET /api/v1/interview/report/{report_id_or_session_id}
    Retrieves a single interview report by report UUID or session ID.
    Enforces user isolation via Supabase RLS.
    """
    report = await get_interview_report_by_id(
        token=auth.token,
        user_id=auth.user_id,
        report_id_or_session_id=report_id_or_session_id,
    )
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview report not found or access denied.",
        )
    return {
        "success": True,
        "report": normalize_report_for_response(report),
    }




