"""
Database Persistence Service — Phase 11

Encapsulates all Supabase PostgreSQL persistence operations for:
  1. resumes
  2. job_descriptions
  3. interview_sessions
  4. interview_questions
  5. candidate_answers
  6. interview_reports

SECURITY & ARCHITECTURE:
  - Connects to Supabase PostgREST using the authenticated user's JWT
    (Authorization: Bearer <user_token> + apikey: <anon_key>).
  - All database queries run under PostgreSQL Row-Level Security (RLS)
    with auth.uid() automatically bound to the calling user.
  - No service-role elevation is needed for standard user operations.
  - Failures are caught and logged so interview flow is never blocked
    by transient network/database errors.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid5, NAMESPACE_URL

import httpx

from app.core.config import settings
from app.services.performance import timed

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_headers(token: str, prefer_merge: bool = False) -> Dict[str, str]:
    headers = {
        "apikey": settings.SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation" if not prefer_merge else "resolution=merge-duplicates,return=representation",
    }
    return headers


def _get_rest_url(table_or_endpoint: str) -> str:
    base = settings.SUPABASE_URL.rstrip("/")
    return f"{base}/rest/v1/{table_or_endpoint}"


# ─────────────────────────────────────────────────────────────────────────────
# 1. RESUME PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

async def persist_resume(
    token: str,
    user_id: UUID,
    file_name: str,
    candidate_profile: Dict[str, Any],
    raw_text: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Persist parsed resume information to public.resumes.
    """
    logger.info('persist_resume: [Persistence] persistence function entered')

    if not settings.SUPABASE_URL or not token:
        logger.warning("[Persistence] Skipped persist_resume: SUPABASE_URL or token missing")
        return None

    url = _get_rest_url("resumes")
    payload = {
        "user_id": str(user_id),
        "file_name": file_name,
        "candidate_profile": candidate_profile,
        "raw_text": raw_text,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, headers=_get_headers(token), json=payload)
            logger.info('persist_resume: [Persistence] PostgREST status')
            if res.status_code in (200, 201):
                records = res.json()
                row = records[0] if isinstance(records, list) and records else records
                row_id = row.get("id") if isinstance(row, dict) else None
                logger.info('persist_resume: [Persistence] insert succeeded')
                return row
            logger.error('persist_resume: [Persistence Error] insert succeeded')
            return None
    except Exception as exc:
        logger.error('persist_resume: [Persistence Error] insert succeeded')
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 2. JOB DESCRIPTION PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

async def persist_job_description(
    token: str,
    user_id: UUID,
    title: str,
    raw_text: str,
    job_profile: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Persist parsed job description to public.job_descriptions.
    """
    logger.info('persist_job_description: [Persistence] persistence function entered')

    if not settings.SUPABASE_URL or not token:
        logger.warning("[Persistence] Skipped persist_job_description: SUPABASE_URL or token missing")
        return None

    url = _get_rest_url("job_descriptions")
    payload = {
        "user_id": str(user_id),
        "title": title or "Software Engineer",
        "raw_text": raw_text,
        "job_profile": job_profile,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, headers=_get_headers(token), json=payload)
            logger.info('persist_job_description: [Persistence] PostgREST status')
            if res.status_code in (200, 201):
                records = res.json()
                row = records[0] if isinstance(records, list) and records else records
                row_id = row.get("id") if isinstance(row, dict) else None
                logger.info('persist_job_description: [Persistence] insert succeeded')
                return row
            logger.error('persist_job_description: [Persistence Error] insert succeeded')
            return None
    except Exception as exc:
        logger.error('persist_job_description: [Persistence Error] insert succeeded')
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 3. INTERVIEW SESSION PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

@timed("db.session_lookup")
async def get_session_db_uuid(token: str, session_id_str: str) -> Optional[str]:
    """
    Resolve the database UUID of an interview_session from its client session_id string.
    """
    if not settings.SUPABASE_URL or not token:
        return None

    url = _get_rest_url(f"interview_sessions?session_id=eq.{session_id_str}&select=id")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, headers=_get_headers(token))
            if res.status_code == 200:
                rows = res.json()
                if rows and isinstance(rows, list) and len(rows) > 0:
                    return rows[0].get("id")
                return None
            logger.error('get_session_db_uuid: [Persistence Error] op=SELECT table=interview_sessions session_id_str=')
    except Exception as exc:
        logger.error('get_session_db_uuid: [Persistence Error] op=SELECT table=interview_sessions session_id_str=')
    return None


async def persist_interview_session(
    token: str,
    user_id: UUID,
    session_id: str,
    role: str,
    interview_type: str,
    difficulty: str,
    interview_mode: str,
    question_count: int,
    interview_config: Dict[str, Any],
    interview_plan: Optional[Dict[str, Any]] = None,
    interview_state: Optional[Dict[str, Any]] = None,
    analysis: Optional[Dict[str, Any]] = None,
    resume_id: Optional[str] = None,
    job_description_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Persist new interview session to public.interview_sessions.
    """
    if not settings.SUPABASE_URL or not token:
        logger.warning("[Persistence] Skipped persist_interview_session: SUPABASE_URL or token missing")
        return None

    url = _get_rest_url("interview_sessions")
    payload = {
        "user_id": str(user_id),
        "session_id": session_id,
        "status": "active",
        "interview_mode": interview_mode,
        "interview_type": interview_type,
        "difficulty": difficulty,
        "role": role,
        "question_count": question_count,
        "interview_config": interview_config or {},
        "interview_plan": interview_plan,
        "interview_state": interview_state,
        "analysis": analysis,
        "resume_id": resume_id,
        "job_description_id": job_description_id,
        "started_at": _now_iso(),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, headers=_get_headers(token, prefer_merge=True), json=payload)
            if res.status_code in (200, 201):
                records = res.json()
                logger.info('persist_interview_session: [Persistence] Successfully persisted session')
                return records[0] if isinstance(records, list) and records else records
            logger.error('persist_interview_session: [Persistence Error] op=INSERT table=interview_sessions user_id=')
            return None
    except Exception as exc:
        logger.error('persist_interview_session: [Persistence Error] op=INSERT table=interview_sessions user_id=')
        return None


@timed("db.session_update")
async def update_interview_session(
    token: str,
    session_id_str: str,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Update an existing interview session by its session_id string.
    """
    if not settings.SUPABASE_URL or not token:
        return None

    url = _get_rest_url(f"interview_sessions?session_id=eq.{session_id_str}")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.patch(url, headers=_get_headers(token), json=updates)
            if res.status_code in (200, 204):
                if res.text:
                    records = res.json()
                    return records[0] if isinstance(records, list) and records else records
                return {"updated": True}
            logger.error('update_interview_session: [Persistence Error] op=PATCH table=interview_sessions session_id_str=')
            return None
    except Exception as exc:
        logger.error('update_interview_session: [Persistence Error] op=PATCH table=interview_sessions session_id_str=')
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. QUESTION PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

@timed("db.question_lookup")
async def get_question_db_uuid(
    token: str,
    session_db_uuid: str,
    question_id_str: str,
    question_order: Optional[int] = None,
) -> Optional[str]:
    """
    Resolve the database UUID of a question from session_db_uuid and question_id string or question_order.
    """
    if not settings.SUPABASE_URL or not token:
        return None

    # First attempt: match by question_id_str
    url = _get_rest_url(
        f"interview_questions?session_id=eq.{session_db_uuid}&question_id=eq.{question_id_str}&select=id"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, headers=_get_headers(token))
            if res.status_code == 200:
                rows = res.json()
                if rows and isinstance(rows, list) and len(rows) > 0:
                    return rows[0].get("id")

            # Fallback attempt: match by question_order if provided
            if question_order is not None:
                order_url = _get_rest_url(
                    f"interview_questions?session_id=eq.{session_db_uuid}&question_order=eq.{question_order}&select=id"
                )
                res_order = await client.get(order_url, headers=_get_headers(token))
                if res_order.status_code == 200:
                    rows = res_order.json()
                    if rows and isinstance(rows, list) and len(rows) > 0:
                        return rows[0].get("id")

            logger.error('get_question_db_uuid: [Persistence Error] op=SELECT table=interview_questions session_id=')
    except Exception as exc:
        logger.error('get_question_db_uuid: [Persistence Error] op=SELECT table=interview_questions session_id=')
    return None


@timed("db.question_save")
async def persist_interview_question(
    token: str,
    session_id_str: str,
    question: Dict[str, Any],
    question_order: int,
    session_db_uuid: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Persist a question to public.interview_questions.
    """
    if not settings.SUPABASE_URL or not token:
        return None

    db_uuid = session_db_uuid or await get_session_db_uuid(token, session_id_str)
    if not db_uuid:
        logger.error('persist_interview_question: [Persistence Error] op=INSERT table=interview_questions reason=missing')
        return None

    existing_id = await get_question_db_uuid(token, db_uuid, question.get("id") or f"q{question_order}", question_order)
    url = _get_rest_url("interview_questions?on_conflict=id")
    payload = {
        "id": existing_id or str(uuid5(NAMESPACE_URL, f"interview-iq:{db_uuid}:question:{question_order}")),
        "session_id": db_uuid,
        "question_id": question.get("id") or f"q{question_order}",
        "question_text": question.get("question") or question.get("question_text", ""),
        "category": question.get("category", "Technical"),
        "topic": question.get("topic", "General"),
        "difficulty": question.get("difficulty", "Medium"),
        "stage": question.get("stage", "TECHNICAL_FUNDAMENTALS"),
        "focus": question.get("focus", "General"),
        "is_follow_up": bool(question.get("is_follow_up", False)),
        "expected_aspects": question.get("expected_aspects") or [],
        "question_order": question_order,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, headers=_get_headers(token, prefer_merge=True), json=payload)
            if res.status_code in (200, 201):
                records = res.json()
                logger.info('persist_interview_question: [Persistence] Successfully persisted question')
                return records[0] if isinstance(records, list) and records else records
            logger.error('persist_interview_question: [Persistence Error] op=INSERT table=interview_questions session_id=')
            return None
    except Exception as exc:
        logger.error('persist_interview_question: [Persistence Error] op=INSERT table=interview_questions session_id=')
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 5. CANDIDATE ANSWER + EVALUATION PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

@timed("db.answer_save")
async def persist_candidate_answer(
    token: str,
    session_id_str: str,
    question_id_str: str,
    answer_text: str,
    skipped: bool,
    timed_out: bool,
    time_spent_secs: int,
    evaluation: Dict[str, Any],
    started_at: Optional[str] = None,
    submitted_at: Optional[str] = None,
    question_order: Optional[int] = None,
    *,
    session_db_uuid: Optional[str] = None,
    question_db_uuid: Optional[str] = None,
    existing_answers: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Persist answer and evaluation record to public.candidate_answers.
    """
    if not settings.SUPABASE_URL or not token:
        return None

    # Internal callers may reuse records already read under this JWT and session lock.
    # Legacy callers still resolve ownership through the same RLS-protected reads.
    session_uuid = session_db_uuid or await get_session_db_uuid(token, session_id_str)
    if not session_uuid:
        logger.error('persist_candidate_answer: [Persistence Error] op=INSERT table=candidate_answers reason=missing_s')
        return None

    question_uuid = question_db_uuid or await get_question_db_uuid(token, session_uuid, question_id_str, question_order)
    if not question_uuid:
        logger.error('persist_candidate_answer: [Persistence Error] op=INSERT table=candidate_answers reason=missing_q')
        return None

    existing = existing_answers if existing_answers is not None else await read_owned_rows(token, "candidate_answers", {"session_id": session_uuid, "question_id": question_uuid})
    url = _get_rest_url("candidate_answers?on_conflict=id")
    payload = {
        "id": existing[0]["id"] if existing else str(uuid5(NAMESPACE_URL, f"interview-iq:{session_uuid}:answer:{question_uuid}")),
        "session_id": session_uuid,
        "question_id": question_uuid,
        "answer_text": answer_text or "",
        "skipped": bool(skipped),
        "timed_out": bool(timed_out),
        "time_spent_secs": max(0, int(time_spent_secs or 0)),
        "score": evaluation.get("score"),
        "technical_accuracy": evaluation.get("technical_accuracy") if evaluation.get("technical_accuracy") is not None else evaluation.get("technicalAccuracy"),
        "clarity": evaluation.get("clarity"),
        "depth": evaluation.get("depth"),
        "relevance": evaluation.get("relevance"),
        "answer_status": evaluation.get("answer_status"),
        "strengths": evaluation.get("strengths") or [],
        "improvements": evaluation.get("improvements") or [],
        "suggested_answer": evaluation.get("suggested_answer") or evaluation.get("suggestedAnswer"),
        "started_at": started_at or _now_iso(),
        "submitted_at": submitted_at or _now_iso(),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, headers=_get_headers(token, prefer_merge=True), json=payload)
            if res.status_code in (200, 201):
                records = res.json()
                logger.info('persist_candidate_answer: [Persistence] Successfully persisted candidate answer for session')
                return records[0] if isinstance(records, list) and records else records
            logger.error('persist_candidate_answer: [Persistence Error] op=INSERT table=candidate_answers session=')
            return None
    except Exception as exc:
        logger.error('persist_candidate_answer: [Persistence Error] op=INSERT table=candidate_answers session=')
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 6. INTERVIEW REPORT PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

@timed("db.report_save")
async def persist_interview_report(
    token: str,
    user_id: UUID,
    session_id_str: str,
    report_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Persist final interview report to public.interview_reports and mark session completed.
    """
    if not settings.SUPABASE_URL or not token:
        return None

    session_uuid = await get_session_db_uuid(token, session_id_str)
    if not session_uuid:
        logger.warning('persist_interview_report: [Persistence] Could not resolve session DB uuid for report')
        return None

    existing = await read_owned_rows(token, "interview_reports", {"session_id": session_uuid})
    report_id = str(uuid5(NAMESPACE_URL, f"interview-iq:{session_uuid}:report"))
    url = _get_rest_url("interview_reports?on_conflict=id")
    overall_score = report_data.get("overall_score") or report_data.get("overallScore") or 0

    payload = {
        "id": report_id,
        "session_id": session_uuid,
        "user_id": str(user_id),
        "overall_score": int(overall_score),
        "role": report_data.get("role") or "Software Engineer",
        "interview_type": report_data.get("interview_type") or report_data.get("interviewType") or "Technical",
        "difficulty": report_data.get("difficulty") or "Medium",
        "questions_answered": int(report_data.get("questions_answered") or report_data.get("questionsAnswered") or 0),
        "total_questions": int(report_data.get("total_questions") or report_data.get("totalQuestions") or 0),
        "duration_secs": int(report_data.get("duration_secs") or report_data.get("durationSecs") or 0),
        "scores": report_data.get("scores") or {},
        "strengths": report_data.get("strengths") or [],
        "skill_gaps": report_data.get("skill_gaps") or report_data.get("skillGaps") or [],
        "recommendations": report_data.get("recommendations") or [],
        "question_analysis": report_data.get("question_analysis") or report_data.get("questionAnalysis") or [],
    }

    try:
        if existing:
            # The report may have been saved immediately before a failed status update.
            report_record = existing[0]
        else:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, headers=_get_headers(token, prefer_merge=True), json=payload)
                if res.status_code not in (200, 201):
                    logger.error('persist_interview_report: [Persistence Error] op=INSERT table=interview_reports session=')
                    return None
                records = res.json()
                report_record = records[0] if isinstance(records, list) and records else records
        if not report_record:
            return None
        completed = await update_interview_session(token, session_id_str, {
            "status": "completed",
            "overall_score": int(report_record.get("overall_score", overall_score)),
            "completed_at": _now_iso(),
        })
        return report_record if completed else None
    except Exception as exc:
        logger.error('persist_interview_report: [Persistence Error] op=INSERT table=interview_reports session=')
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 7. INTERVIEW HISTORY RETRIEVAL
# ─────────────────────────────────────────────────────────────────────────────

async def get_user_interview_reports(
    token: str,
    user_id: UUID,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Fetch user's historical interview reports from public.interview_reports.
    Protected by RLS (only returns authenticated user's records).
    """
    if not settings.SUPABASE_URL or not token:
        return []

    url = _get_rest_url(f"interview_reports?user_id=eq.{user_id}&select=*&order=created_at.desc&limit={limit}")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, headers=_get_headers(token))
            if res.status_code == 200:
                rows = res.json()
                return rows if isinstance(rows, list) else []
            logger.error('get_user_interview_reports: [Persistence Error] op=SELECT table=interview_reports user_id=')
            return []
    except Exception as exc:
        logger.error('get_user_interview_reports: [Persistence Error] op=SELECT table=interview_reports user_id=')
        return []


async def get_user_interview_sessions(
    token: str,
    user_id: UUID,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Fetch user's historical interview sessions joined with their report metadata.
    Protected by Supabase RLS (only returns authenticated user's records).
    """
    if not settings.SUPABASE_URL or not token:
        return []

    url = _get_rest_url(
        f"interview_sessions?user_id=eq.{user_id}"
        f"&select=id,session_id,role,status,interview_type,difficulty,interview_mode,question_count,overall_score,started_at,completed_at,created_at,resume_id,job_description_id,interview_reports(id,overall_score,duration_secs,questions_answered,total_questions)"
        f"&order=created_at.desc&limit={limit}"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, headers=_get_headers(token))
            if res.status_code == 200:
                rows = res.json()
                if not isinstance(rows, list):
                    return []
                results = []
                for s in rows:
                    rep = s.get("interview_reports")
                    if isinstance(rep, list) and len(rep) > 0:
                        rep = rep[0]
                    elif not isinstance(rep, dict):
                        rep = None

                    has_report = rep is not None
                    report_id = rep.get("id") if rep else None

                    # Score: session overall_score or report overall_score
                    score = s.get("overall_score")
                    if score is None and rep and rep.get("overall_score") is not None:
                        score = rep.get("overall_score")

                    # Duration: report duration_secs or timestamp difference
                    duration_secs = rep.get("duration_secs") if rep else 0
                    if not duration_secs and s.get("started_at") and s.get("completed_at"):
                        try:
                            from datetime import datetime
                            t1 = datetime.fromisoformat(s["started_at"].replace("Z", "+00:00"))
                            t2 = datetime.fromisoformat(s["completed_at"].replace("Z", "+00:00"))
                            duration_secs = max(0, int((t2 - t1).total_seconds()))
                        except Exception:
                            duration_secs = 0

                    results.append({
                        "id": s.get("id"),
                        "session_id": s.get("session_id"),
                        "session_uuid": s.get("id"),
                        "role": s.get("role") or "Software Engineer",
                        "interview_type": s.get("interview_type") or "Technical",
                        "difficulty": s.get("difficulty") or "Medium",
                        "interview_mode": s.get("interview_mode") or "STATIC",
                        "status": s.get("status") or "active",
                        "question_count": s.get("question_count") or (rep.get("total_questions") if rep else 0),
                        "questions_answered": rep.get("questions_answered") if rep else (s.get("question_count") if s.get("status") == "completed" else 0),
                        "overall_score": score,
                        "duration_secs": duration_secs or 0,
                        "started_at": s.get("started_at"),
                        "completed_at": s.get("completed_at"),
                        "created_at": s.get("created_at"),
                        "resume_id": s.get("resume_id"),
                        "job_description_id": s.get("job_description_id"),
                        "has_report": has_report,
                        "report_id": report_id,
                    })
                return results

            logger.error('get_user_interview_sessions: [Persistence Error] op=SELECT table=interview_sessions user_id=')
            return []
    except Exception as exc:
        logger.error('get_user_interview_sessions: [Persistence Error] op=SELECT table=interview_sessions user_id=')
        return []


async def get_interview_report_by_id(
    token: str,
    user_id: UUID,
    report_id_or_session_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Fetch a single interview report by report UUID or session ID / session UUID.
    Protected by Supabase RLS.
    """
    if not settings.SUPABASE_URL or not token:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Attempt lookup by report PK id
            url1 = _get_rest_url(f"interview_reports?user_id=eq.{user_id}&id=eq.{report_id_or_session_id}&select=*")
            res1 = await client.get(url1, headers=_get_headers(token))
            if res1.status_code == 200:
                rows = res1.json()
                if rows and isinstance(rows, list) and len(rows) > 0:
                    return rows[0]

            # 2. Attempt lookup by session_id (FK UUID in interview_reports)
            url2 = _get_rest_url(f"interview_reports?user_id=eq.{user_id}&session_id=eq.{report_id_or_session_id}&select=*")
            res2 = await client.get(url2, headers=_get_headers(token))
            if res2.status_code == 200:
                rows = res2.json()
                if rows and isinstance(rows, list) and len(rows) > 0:
                    return rows[0]

            # 3. Attempt lookup via client session string (e.g., 'session-1234')
            session_uuid = await get_session_db_uuid(token, report_id_or_session_id)
            if session_uuid:
                url3 = _get_rest_url(f"interview_reports?user_id=eq.{user_id}&session_id=eq.{session_uuid}&select=*")
                res3 = await client.get(url3, headers=_get_headers(token))
                if res3.status_code == 200:
                    rows = res3.json()
                    if rows and isinstance(rows, list) and len(rows) > 0:
                        return rows[0]

    except Exception as exc:
        logger.error('get_interview_report_by_id: [Persistence Error] op=SELECT table=interview_reports identifier=')
    return None


async def get_user_dashboard_analytics(
    token: str,
    user_id: UUID,
) -> Dict[str, Any]:
    """
    Compute real, database-backed analytics and statistics for the authenticated user.
    Strictly derives metrics from live records in:
      - public.interview_sessions
      - public.interview_reports
      - public.candidate_answers
      - public.profiles
    Never returns mock, simulated, or fabricated data.
    """
    default_response = {
        "total_interviews": 0,
        "completed_interviews": 0,
        "in_progress_interviews": 0,
        "average_score": 0,
        "score_trend": [],
        "performance_dimensions": {
            "technical_accuracy": 0,
            "clarity": 0,
            "depth": 0,
            "relevance": 0,
        },
        "top_strengths": [],
        "top_improvements": [],
        "recent_interviews": [],
        "skills_identified": 0,
    }

    if not settings.SUPABASE_URL or not token:
        return default_response

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = _get_headers(token)

            # 1. Fetch user sessions with report overview
            sess_url = _get_rest_url(
                f"interview_sessions?user_id=eq.{user_id}"
                f"&select=id,session_id,role,status,overall_score,interview_type,difficulty,created_at,started_at,completed_at,interview_reports(id,overall_score,duration_secs,scores,strengths,skill_gaps)"
                f"&order=created_at.desc"
            )
            sess_res = await client.get(sess_url, headers=headers)
            sessions = sess_res.json() if sess_res.status_code == 200 and isinstance(sess_res.json(), list) else []

            # 2. Fetch candidate answers for performance dimension analysis
            ans_url = _get_rest_url(
                f"candidate_answers?select=score,technical_accuracy,clarity,depth,relevance,strengths,improvements&limit=200"
            )
            ans_res = await client.get(ans_url, headers=headers)
            answers = ans_res.json() if ans_res.status_code == 200 and isinstance(ans_res.json(), list) else []

            # 3. Fetch profile skills count
            prof_url = _get_rest_url(f"profiles?id=eq.{user_id}&select=skills")
            prof_res = await client.get(prof_url, headers=headers)
            prof_data = prof_res.json() if prof_res.status_code == 200 and isinstance(prof_res.json(), list) and prof_res.json() else []
            profile_skills = prof_data[0].get("skills") or [] if prof_data else []

            # Calculate Core Metrics
            total_interviews = len(sessions)
            completed_sessions = [s for s in sessions if s.get("status") == "completed"]
            completed_count = len(completed_sessions)
            in_progress_count = len([s for s in sessions if s.get("status") == "active"])

            # Valid final scores for average score calculation:
            # Inclusion rule: completed sessions only, with non-null score >= 0
            valid_scores = []
            for s in completed_sessions:
                score = s.get("overall_score")
                if score is None and s.get("interview_reports"):
                    rep = s["interview_reports"][0] if isinstance(s["interview_reports"], list) and s["interview_reports"] else s["interview_reports"]
                    if isinstance(rep, dict):
                        score = rep.get("overall_score")
                if score is not None and isinstance(score, (int, float)) and score >= 0:
                    valid_scores.append(int(score))

            average_score = round(sum(valid_scores) / len(valid_scores)) if valid_scores else 0

            # Score trend (chronological order)
            # Sort completed sessions by created_at ascending
            sorted_completed = sorted(completed_sessions, key=lambda x: x.get("created_at") or "")
            score_trend = []
            for s in sorted_completed:
                sc = s.get("overall_score")
                if sc is None and s.get("interview_reports"):
                    rep = s["interview_reports"][0] if isinstance(s["interview_reports"], list) and s["interview_reports"] else s["interview_reports"]
                    if isinstance(rep, dict):
                        sc = rep.get("overall_score")
                if sc is not None:
                    score_trend.append({
                        "date": s.get("created_at") or s.get("started_at"),
                        "score": int(sc),
                        "role": s.get("role") or "Software Engineer",
                    })

            # Performance Dimensions (Technical Accuracy, Clarity, Depth, Relevance)
            tech_vals = [a["technical_accuracy"] for a in answers if a.get("technical_accuracy") is not None]
            clarity_vals = [a["clarity"] for a in answers if a.get("clarity") is not None]
            depth_vals = [a["depth"] for a in answers if a.get("depth") is not None]
            relevance_vals = [a["relevance"] for a in answers if a.get("relevance") is not None]

            # Fallback to report scores if candidate_answers have no dimension fields yet
            if not tech_vals and completed_sessions:
                for s in completed_sessions:
                    rep = s.get("interview_reports")
                    if isinstance(rep, list) and rep:
                        rep = rep[0]
                    if isinstance(rep, dict) and isinstance(rep.get("scores"), dict):
                        rep_scores = rep["scores"]
                        t_val = rep_scores.get("technicalAccuracy") or rep_scores.get("technicalKnowledge")
                        c_val = rep_scores.get("communication") or rep_scores.get("clarity")
                        d_val = rep_scores.get("problemSolving") or rep_scores.get("depth")
                        r_val = rep_scores.get("experienceMatch") or rep_scores.get("jobRelevance") or rep_scores.get("relevance")
                        if t_val is not None: tech_vals.append(int(t_val))
                        if c_val is not None: clarity_vals.append(int(c_val))
                        if d_val is not None: depth_vals.append(int(d_val))
                        if r_val is not None: relevance_vals.append(int(r_val))

            dimensions = {
                "technical_accuracy": round(sum(tech_vals) / len(tech_vals)) if tech_vals else 0,
                "clarity": round(sum(clarity_vals) / len(clarity_vals)) if clarity_vals else 0,
                "depth": round(sum(depth_vals) / len(depth_vals)) if depth_vals else 0,
                "relevance": round(sum(relevance_vals) / len(relevance_vals)) if relevance_vals else 0,
            }

            # Top Strengths and Improvements Aggregation
            strengths_list = []
            improvements_list = []

            for a in answers:
                if isinstance(a.get("strengths"), list):
                    strengths_list.extend([str(item) for item in a["strengths"] if item])
                if isinstance(a.get("improvements"), list):
                    improvements_list.extend([str(item) for item in a["improvements"] if item])

            for s in completed_sessions:
                rep = s.get("interview_reports")
                if isinstance(rep, list) and rep:
                    rep = rep[0]
                if isinstance(rep, dict):
                    if isinstance(rep.get("strengths"), list):
                        strengths_list.extend([str(item) for item in rep["strengths"] if item])
                    if isinstance(rep.get("skill_gaps"), list):
                        improvements_list.extend([str(item) for item in rep["skill_gaps"] if item])

            # Deduplicate keeping most frequent
            from collections import Counter
            top_strengths = [item for item, _ in Counter(strengths_list).most_common(5)]
            top_improvements = [item for item, _ in Counter(improvements_list).most_common(5)]

            # Skills identified count
            all_known_skills = set(profile_skills)
            for item in strengths_list:
                if len(item) < 30: # likely a skill name rather than long sentence
                    all_known_skills.add(item)
            skills_count = max(len(profile_skills), len(all_known_skills))

            # Recent interviews (top 5 formatted)
            recent_interviews = []
            for s in sessions[:5]:
                rep = s.get("interview_reports")
                if isinstance(rep, list) and rep:
                    rep = rep[0]
                elif not isinstance(rep, dict):
                    rep = None

                sc = s.get("overall_score")
                if sc is None and rep:
                    sc = rep.get("overall_score")

                dur = rep.get("duration_secs") if rep else 0

                recent_interviews.append({
                    "id": rep.get("id") if rep else s.get("id"),
                    "session_id": s.get("session_id"),
                    "session_uuid": s.get("id"),
                    "role": s.get("role") or "Software Engineer",
                    "type": s.get("interview_type") or "Technical",
                    "difficulty": s.get("difficulty") or "Medium",
                    "status": "Completed" if s.get("status") == "completed" else "In Progress" if s.get("status") == "active" else "Abandoned",
                    "score": int(sc) if sc is not None else 0,
                    "duration": f"{max(1, round(dur / 60))} min" if dur else "0 min",
                    "date": s.get("created_at") or s.get("started_at"),
                    "has_report": rep is not None,
                    "report_id": rep.get("id") if rep else None,
                })

            return {
                "total_interviews": total_interviews,
                "completed_interviews": completed_count,
                "in_progress_interviews": in_progress_count,
                "average_score": average_score,
                "score_trend": score_trend,
                "performance_dimensions": dimensions,
                "top_strengths": top_strengths,
                "top_improvements": top_improvements,
                "recent_interviews": recent_interviews,
                "skills_identified": skills_count,
            }

    except Exception as exc:
        logger.error('get_user_dashboard_analytics: [Persistence Error] op=get_user_dashboard_analytics user_id=')
        return default_response



@timed("db.owned_read")
async def read_owned_rows(token: str, table: str, filters: dict) -> list:
    """Read rows under the caller JWT/RLS. Query parameters are URL encoded by httpx."""
    allowed = {"resumes", "job_descriptions", "interview_sessions", "interview_questions", "candidate_answers", "interview_reports"}
    if table not in allowed:
        raise ValueError("Unsupported interview table")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(_get_rest_url(table), headers=_get_headers(token),
                                    params={**{key: f"eq.{value}" for key, value in filters.items()}, "select": "*"})
        response.raise_for_status()
        return response.json()
