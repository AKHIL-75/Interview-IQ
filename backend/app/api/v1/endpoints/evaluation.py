"""
Phase 10: Answer Evaluation API Endpoint.
Exposes POST /api/v1/evaluation/evaluate for AI-powered answer assessment.
"""
from app.services.llm_service import OpenRouterError, LLMTimeoutError


import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import AuthUser, get_optional_auth
from app.core.inference import session_engine
from app.schemas.evaluation import (
    AnswerEvaluationRequest, AnswerEvaluationResponse, CONCEPTUAL_RUBRIC, saved_answer_rubric,
)
from app.services.interview_commit import session_lock
from app.services.persistence_service import read_owned_rows, persist_candidate_answer, update_interview_session
from app.services.evaluator import evaluate_candidate_answer
from app.services.performance import metric
from app.services.llm_service import (
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
    LLMResponseParseError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/evaluate",
    response_model=AnswerEvaluationResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate candidate interview answer",
    description=(
        "Scores conceptual correctness, relevance, and clarity with deterministic weighting and structured feedback."
    ),
)
async def evaluate_answer(
    request: AnswerEvaluationRequest,
    auth: Optional[AuthUser] = Depends(get_optional_auth),
) -> AnswerEvaluationResponse:
    """
    POST /api/v1/evaluation/evaluate

    Request:
        {
            "question": "...",
            "candidate_answer": "...",
            "expected_answer": "...",
            "job_title": "...",
            "category": "Technical",
            "difficulty": "Medium",
            "relevant_skills": [...]
        }

    Response:
        {
            "score": 0,
            "technicalAccuracy": 0,
            "clarity": 0,
            "depth": 0,
            "relevance": 0,
            "strengths": [...],
            "improvements": [...],
            "suggestedAnswer": "..."
        }
    """
    metric("evaluation.validated")
    try:
        if not request.session_id:
            return await evaluate_candidate_answer(request)
        if not auth:
            raise HTTPException(401, "Authentication is required to save an interview answer.")
        async with session_lock((str(auth.user_id), request.session_id)):
            sessions = await read_owned_rows(auth.token, "interview_sessions", {"session_id": request.session_id})
            if not sessions:
                raise HTTPException(404, "Interview session not found.")
            session = sessions[0]
            destination = session_engine(session)
            config = session.get("interview_config") or {}
            rubric = saved_answer_rubric(config, request.question_id)
            questions = await read_owned_rows(auth.token, "interview_questions", {"session_id": session["id"]})
            questions.sort(key=lambda q: q["question_order"])
            current = next((q for q in questions if q["question_id"] == request.question_id), None)
            if not current or current["question_text"] != request.question:
                raise HTTPException(409, "Question does not match the saved session.")
            saved = await read_owned_rows(auth.token, "candidate_answers", {"session_id": session["id"], "question_id": current["id"]})
            if saved:
                row = saved[0]
                if row["answer_text"] != request.candidate_answer:
                    raise HTTPException(409, "This question already has a saved answer.")
                return AnswerEvaluationResponse(score=row["score"], technicalAccuracy=row["technical_accuracy"],
                    relevance=row["relevance"], depth=row["depth"], clarity=row["clarity"], rubric_version=rubric,
                    answer_status=row.get("answer_status") or "PARTIAL", strengths=row.get("strengths") or [],
                    improvements=row.get("improvements") or [], suggestedAnswer=row.get("suggested_answer") or "")
            if session.get("status") == "completed" or current != questions[-1]:
                raise HTTPException(409, "Only the current question can be evaluated.")
            request.category = current.get("category") or request.category
            request.stage = current.get("stage") or request.stage
            request.topic = current.get("topic") or request.topic
            request.difficulty = current.get("difficulty") or request.difficulty
            request.expected_answer = "; ".join(current.get("expected_aspects") or []) or None
            request.relevant_skills = [request.topic] if request.topic else []
            with destination:
                response = await evaluate_candidate_answer(request)
            if response.rubric_version == CONCEPTUAL_RUBRIC and rubric is None:
                # Sessions already in progress can contain answers evaluated under both rubrics.
                # Record the new answer's rubric before saving its score so a retry can replay it.
                config = {**config, "conceptual_question_ids": [
                    *(config.get("conceptual_question_ids") or []), request.question_id,
                ]}
                if not await update_interview_session(auth.token, request.session_id, {"interview_config": config}):
                    raise HTTPException(503, "Evaluation could not be saved. Your answer is preserved; retry.")
            saved = await persist_candidate_answer(auth.token, request.session_id, request.question_id,
                request.candidate_answer, False, False, 0, response.model_dump(), question_order=current["question_order"],
                session_db_uuid=session["id"], question_db_uuid=current["id"], existing_answers=saved)
            if not saved:
                raise HTTPException(503, "Evaluation could not be saved. Your answer is preserved; retry.")
            return response

    except OpenRouterError as err:
        raise HTTPException(err.status_code, "The inference provider could not complete the request.") from None
    except OllamaConnectionError as exc:
        logger.error('evaluate_answer: [EvaluationEndpoint] Ollama connection error')
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI evaluation service is temporarily unavailable: {exc}",
        )
    except OllamaModelNotFoundError as exc:
        logger.error('evaluate_answer: [EvaluationEndpoint] Ollama model not found')
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Required model for evaluation is not available: {exc}",
        )
    except LLMTimeoutError as exc:
        logger.error('evaluate_answer: [EvaluationEndpoint] Ollama timeout')
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"AI evaluation timed out: {exc}",
        )
    except LLMResponseParseError as exc:
        logger.error('evaluate_answer: [EvaluationEndpoint] LLM JSON parse error')
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI returned malformed evaluation response: {exc}",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error('evaluate_answer: [EvaluationEndpoint] Unexpected error')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during answer evaluation: {str(exc)}",
        )
