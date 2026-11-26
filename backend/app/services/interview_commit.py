from app.services.performance import timed
"""Serialize session commits and replay durable adaptive results after network retries."""
import asyncio
from contextlib import asynccontextmanager
from app.services.persistence_service import read_owned_rows, persist_candidate_answer, persist_interview_question, update_interview_session
from app.services.adaptive_interviewer import process_adaptive_next_question
from app.schemas.adaptive import AdaptiveNextQuestionResponse, AdaptiveEvaluationInput
from fastapi import HTTPException
from app.core.inference import session_engine
from app.services.question_policy import saved_interview_type, category_matches

_locks = {}

@asynccontextmanager
async def session_lock(key):
    entry = _locks.setdefault(key, {"lock": asyncio.Lock(), "users": 0})
    entry["users"] += 1
    try:
        async with entry["lock"]:
            yield
    finally:
        entry["users"] -= 1
        if not entry["users"]:
            _locks.pop(key, None)

@timed("adaptive.commit")
async def commit_answer(request, auth):
    if not request.session_id:
        raise HTTPException(422, "A persisted session ID is required.")
    async with session_lock((str(auth.user_id), request.session_id)):
        sessions = await read_owned_rows(auth.token, "interview_sessions", {"session_id": request.session_id})
        if not sessions:
            raise HTTPException(404, "Interview session not found.")
        session = sessions[0]
        destination = session_engine(session)
        try:
            interview_type = saved_interview_type(session)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        state = session.get("interview_state") or {}
        record = request.answer_history[-1] if request.answer_history else {}
        question_id = record.get("questionId")
        if not question_id or not request.candidate_answer.strip():
            raise HTTPException(422, "Question identity and a candidate answer are required.")
        checkpoint = state.get("_submission") or {}
        if checkpoint.get("question_id") == question_id:
            if checkpoint.get("answer") != request.candidate_answer:
                raise HTTPException(409, "This question already has a saved answer.")
            response = AdaptiveNextQuestionResponse.model_validate(checkpoint["response"])
            if response.question and (not category_matches(response.question.question, response.question.category)
                    or (interview_type != "Mixed" and response.question.category != interview_type)):
                raise HTTPException(409, "Saved next question conflicts with interview type. Session data is preserved; restore the checkpoint before continuing.")
            if checkpoint.get("committed"):
                return response
        else:
            if session.get("status") == "completed":
                raise HTTPException(409, "This interview is already complete.")
            questions = await read_owned_rows(auth.token, "interview_questions", {"session_id": session["id"]})
            questions.sort(key=lambda q: q["question_order"])
            current = questions[-1] if questions else None
            if not current or current["question_id"] != question_id or current["question_text"] != request.previous_question:
                raise HTTPException(409, "Refresh to the current saved question before answering.")
            request.question_history = [q["question_text"] for q in questions]
            request.interview_plan = {**(session.get("interview_plan") or {}), "interview_type": interview_type}
            request.interview_state = {k: v for k, v in state.items() if k != "_submission"}
            request.interview_state["category_counts"] = {c: sum(q.get("category") == c for q in questions) for c in ("HR", "Technical")}
            request.difficulty = current.get("difficulty") or request.difficulty
            request.current_topic = current.get("topic") or request.current_topic
            request.category = current.get("category") or request.category
            request.relevant_skills = [request.current_topic]
            request.consecutive_follow_ups = state.get("consecutive_follow_ups", 0)
            all_answers = await read_owned_rows(auth.token, "candidate_answers", {"session_id": session["id"]})
            stored_answers = [a for a in all_answers if a.get("question_id") == current["id"]]
            request.answer_history = [
                {"question": q["question_text"], "answer": a.get("answer_text", ""),
                 "evaluation": {"score": a.get("score"), "technicalAccuracy": a.get("technical_accuracy"),
                                "relevance": a.get("relevance"), "clarity": a.get("clarity"),
                                "answer_status": a.get("answer_status"),
                                "improvements": a.get("improvements") or []}}
                for q in questions for a in all_answers if a.get("question_id") == q["id"]]
            if not stored_answers or stored_answers[0].get("answer_text") != request.candidate_answer:
                raise HTTPException(409, "Evaluate and save this answer before requesting the next question.")
            saved_answer = stored_answers[0]
            request.evaluation = AdaptiveEvaluationInput(
                score=saved_answer["score"], technicalAccuracy=saved_answer["technical_accuracy"],
                relevance=saved_answer["relevance"], clarity=saved_answer["clarity"],
                answer_status=saved_answer.get("answer_status"), strengths=saved_answer.get("strengths") or [],
                improvements=saved_answer.get("improvements") or [], suggestedAnswer=saved_answer.get("suggested_answer") or "")
            with destination:
                response = await process_adaptive_next_question(request)
            checkpoint = {"question_id": question_id, "answer": request.candidate_answer,
                          "response": response.model_dump(), "committed": False}
            # Save generated result before dependent writes: retry reuses Qwen output.
            if not await update_interview_session(auth.token, request.session_id,
                    {"interview_state": {**state, "_submission": checkpoint}}):
                raise HTTPException(503, "Adaptive result could not be saved. Retry to continue.")
        if response.question:
            questions_asked = (response.interview_state or {}).get("questions_asked") or len(request.question_history) + 1
            saved_question = await persist_interview_question(auth.token, request.session_id,
                response.question.model_dump(), questions_asked, session_db_uuid=session["id"])
            if not saved_question:
                raise HTTPException(503, "Next question could not be saved. Retry to continue.")
        checkpoint = {**checkpoint, "committed": True}
        if not await update_interview_session(auth.token, request.session_id, {
            "interview_plan": response.interview_plan,
            "interview_state": {**(response.interview_state or {}), "_submission": checkpoint},
        }):
            raise HTTPException(503, "Interview progress could not be saved. Retry to continue.")
        return response
