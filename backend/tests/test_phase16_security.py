"""Isolated fault injection; does not claim live service/hardware verification."""
import asyncio
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.auth import AuthUser, get_current_auth
from app.core.config import settings
from app.core.exceptions import install_exception_handlers
from app.core.request_limits import LocalRateLimiter, RequestLimitsMiddleware
from app.schemas.evaluation import AnswerEvaluationRequest
from app.schemas.adaptive import InterviewStartRequest, AdaptiveNextQuestionRequest
from app.schemas.job import JobParseRequest
from app.services.resume_parser import parse_resume_file, FileTooLargeError
from app.api.v1.endpoints import audio, evaluation, resume, interview
from app.services.stt_service import TranscriptionError
from app.services.llm_service import OllamaConnectionError, OllamaTimeoutError, LLMResponseParseError

SECRET = 'private-answer-token-internal-path'


def test_app(authenticated=False):
    app = FastAPI()
    install_exception_handlers(app)
    app.add_middleware(RequestLimitsMiddleware)
    app.include_router(audio.router, prefix='/api/v1/audio')
    app.include_router(evaluation.router, prefix='/api/v1/evaluation')
    app.include_router(resume.router, prefix='/api/v1/resume')
    if authenticated:
        app.dependency_overrides[get_current_auth] = lambda: AuthUser(uuid4(), 'synthetic-auth')
    return app


# Factory is not a test.
test_app.__test__ = False


@pytest.mark.parametrize('status', [400, 401, 403, 404, 409, 413, 415, 422, 429, 500, 502, 503, 504])
def test_http_errors_do_not_disclose_details(status):
    app = test_app()
    @app.get('/failure')
    def failure():
        raise HTTPException(status, SECRET, headers={'X-Private': SECRET, 'Retry-After': '10'})
    response = TestClient(app).get('/failure')
    assert response.status_code == status
    assert response.json()['status'] == status
    assert response.headers['content-type'] == 'application/problem+json'
    assert response.headers['x-request-id'] == response.json()['request_id']
    assert SECRET not in response.text and 'x-private' not in response.headers
    assert response.headers['retry-after'] == '10'


def test_unexpected_exception_is_safe(caplog):
    app = test_app()
    @app.get('/failure')
    def failure():
        raise RuntimeError(SECRET)
    result = TestClient(app, raise_server_exceptions=False).get('/failure')
    assert result.status_code == 500
    assert SECRET not in result.text + caplog.text
    assert 'RuntimeError' in caplog.text


@pytest.mark.parametrize('payload', [{'question': SECRET}, {'question': 'Valid question', 'candidate_answer': '   '}, {'question': 'Valid question', 'candidate_answer': 'x' * 20001}])
def test_validation_suppresses_submitted_values(payload):
    result = TestClient(test_app()).post('/api/v1/evaluation/evaluate', json=payload)
    assert result.status_code == 422
    assert SECRET not in result.text and 'input' not in result.json()


def test_invalid_json_is_safe():
    result = TestClient(test_app()).post('/api/v1/evaluation/evaluate', content='{"secret":', headers={'Content-Type': 'application/json'})
    assert result.status_code == 422 and 'secret' not in result.text


@pytest.mark.parametrize('change', [{'session_id': '../invalid'}, {'question_id': 'x&or=true'}, {'difficulty': 'Impossible'}, {'category': 'Unknown'}, {'candidate_answer': None}, {'extra_user_id': 'attacker'}])
def test_evaluation_rejects_bad_inputs(change):
    with pytest.raises(ValidationError):
        AnswerEvaluationRequest.model_validate({'question': 'Explain SQL', 'candidate_answer': 'A valid answer', **change})


@pytest.mark.parametrize('change', [{'question_count': 0}, {'question_count': 21}, {'question_count': True}, {'mode': 'Surveillance'}, {'interview_type': 'Unknown'}, {'interview_mode': 'OTHER'}])
def test_interview_configuration(change):
    with pytest.raises(ValidationError):
        InterviewStartRequest.model_validate(change)


@pytest.mark.parametrize('value', ['', ' ' * 30, 'x' * 50001], ids=['empty','whitespace','oversized'])
def test_jd_bounds(value):
    with pytest.raises(ValidationError):
        JobParseRequest(text=value)


def test_rate_window_and_bounded_memory():
    now = [0]
    limiter = LocalRateLimiter(limit=2, window=60, capacity=2, clock=lambda: now[0])
    assert limiter.retry_after('a') == limiter.retry_after('a') == 0
    assert limiter.retry_after('a') == 60
    assert limiter.retry_after('b') == 0
    assert limiter.retry_after('c') == 60
    assert len(limiter.clients) == 2
    now[0] = 61
    assert limiter.retry_after('a') == 0


def test_rate_limit_does_not_trust_forwarded_ip_or_call_endpoint():
    app = FastAPI()
    app.add_middleware(RequestLimitsMiddleware, limiter=LocalRateLimiter(limit=1))
    calls = []
    @app.post('/api/v1/audio/transcribe')
    def work(): calls.append(1); return {'ok': True}
    client = TestClient(app)
    assert client.post('/api/v1/audio/transcribe').status_code == 200
    response = client.post('/api/v1/audio/transcribe', headers={'X-Forwarded-For': 'other'})
    assert response.status_code == 429 and response.headers['retry-after']
    assert len(calls) == 1


def test_guest_capable_routes_share_budget_without_requiring_login():
    app = FastAPI()
    app.add_middleware(RequestLimitsMiddleware, api_prefix="/custom")

    @app.post("/custom/{group}/{operation}")
    def accepted(group: str, operation: str):
        return {"ok": True}

    client = TestClient(app)
    for _ in range(10):
        assert client.post("/custom/job/parse").status_code == 200
        assert client.post("/custom/analysis/match").status_code == 200
    response = client.post("/custom/evaluation/evaluate", headers={
        "Authorization": "Bearer unverified-value",
        "X-Forwarded-For": "198.51.100.1",
    })
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    assert "unverified-value" not in response.text
    assert client.post("/custom/interview/start").status_code == 200


def test_diagnostic_has_separate_budget():
    app = FastAPI()
    app.add_middleware(RequestLimitsMiddleware)
    app.post("/api/v1/ai/test")(lambda: {"ok": True})
    app.post("/api/v1/job/parse")(lambda: {"ok": True})

    client = TestClient(app)
    assert client.post("/api/v1/ai/test").status_code == 200
    assert client.post("/api/v1/ai/test").status_code == 200
    assert client.post("/api/v1/ai/test").status_code == 429
    assert client.post("/api/v1/job/parse").status_code == 200


def test_guest_capable_admission_releases_slots_after_disconnect_and_cancellation():
    async def run():
        reached = asyncio.Event()
        count = 0

        async def downstream(scope, receive, send):
            nonlocal count
            count += 1
            if count == 4:
                reached.set()
            await asyncio.Future()

        middleware = RequestLimitsMiddleware(downstream)
        async def request(peer, disconnected=False, forwarded=False):
            replies = []
            async def receive():
                return {"type": "http.disconnect" if disconnected else "http.request"}
            async def send(message):
                replies.append(message)
            await middleware({
                "type": "http", "method": "POST", "path": "/api/v1/resume/parse",
                "client": (peer, 4000),
                "headers": [(b"x-forwarded-for", b"198.51.100.200")] if forwarded else [],
            }, receive, send)
            return replies

        tasks = [asyncio.create_task(request(peer)) for peer in ("a", "a", "b", "b")]
        try:
            await asyncio.wait_for(reached.wait(), timeout=2)
            assert (await request("a", forwarded=True))[0]["status"] == 429
            assert (await request("c"))[0]["status"] == 429
            tasks[3].cancel()
            await asyncio.gather(tasks[3], return_exceptions=True)
            assert (await request("a", forwarded=True))[0]["status"] == 429
            assert not await request("c", disconnected=True)
            assert "c" not in middleware.active_by_peer
            assert middleware.active_guest_capable == 3
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert middleware.active_guest_capable == 0
        assert middleware.active_by_peer == {}

    asyncio.run(run())


def test_chunked_size_guard_before_application():
    calls = []
    async def app(*args): calls.append(1)
    chunks = iter([{'type': 'http.request', 'body': b'x' * (1024 * 1024), 'more_body': True},
                   {'type': 'http.request', 'body': b'x', 'more_body': False}])
    sent = []
    async def receive(): return next(chunks)
    async def send(msg): sent.append(msg)
    asyncio.run(RequestLimitsMiddleware(app)({'type':'http','method':'POST','path':'/other','headers':[]}, receive, send))
    assert sent[0]['status'] == 413 and not calls


@pytest.mark.parametrize('failure,expected', [(OllamaConnectionError(SECRET),503), (OllamaTimeoutError(SECRET),504), (LLMResponseParseError(SECRET),502)])
def test_evaluation_failures_do_not_save_or_disclose(failure, expected, caplog):
    with patch.object(evaluation, 'evaluate_candidate_answer', AsyncMock(side_effect=failure)), patch.object(evaluation, 'persist_candidate_answer', AsyncMock()) as save:
        response = TestClient(test_app()).post('/api/v1/evaluation/evaluate', json={'question':'Explain transactions','candidate_answer':'An atomic unit of work'})
    assert response.status_code == expected
    save.assert_not_awaited()
    assert SECRET not in response.text + caplog.text


def test_auth_outage_is_not_invalid_session():
    request = httpx.Request('GET', 'https://example.invalid')
    with patch.object(settings, 'SUPABASE_URL', 'https://example.invalid'), patch.object(settings, 'SUPABASE_ANON_KEY', 'test-public-key'), patch('app.core.auth.httpx.AsyncClient') as client:
        client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=httpx.ConnectError(SECRET, request=request))
        with pytest.raises(HTTPException) as err:
            asyncio.run(get_current_auth(HTTPAuthorizationCredentials(scheme='Bearer', credentials='test-token')))
    assert err.value.status_code == 503 and SECRET not in err.value.detail


def test_missing_auth_is_rejected():
    with pytest.raises(HTTPException) as err:
        asyncio.run(get_current_auth(None))
    assert err.value.status_code == 401


@pytest.mark.parametrize('failure', [False, True])
def test_audio_temp_cleanup_success_failure(failure, caplog):
    paths = []
    async def transcribe(path, vad_filter, request):
        paths.append(path)
        assert Path(path).exists()
        if failure: raise TranscriptionError(SECRET)
        return dict(success=True,text='Exact original words',duration_seconds=1,model='test-adapter')
    with patch('app.services.stt_provider.transcribe_with_provider', new_callable=AsyncMock) as service:
        service.side_effect = transcribe
        response = TestClient(test_app(authenticated=True)).post('/api/v1/audio/transcribe', files={'file':('../../private.webm',b'test','audio/webm')})
    assert response.status_code == (422 if failure else 200)
    assert paths and all(not Path(p).exists() for p in paths)
    assert SECRET not in response.text + caplog.text
    if not failure: assert response.json()['text'] == 'Exact original words'


@pytest.mark.parametrize('content,mime,status', [(b'', 'audio/webm',400),(b'test','text/plain',415)])
def test_invalid_audio_never_transcribes(content,mime,status):
    with patch('app.services.stt_provider.transcribe_with_provider', new_callable=AsyncMock) as service:
        result=TestClient(test_app(authenticated=True)).post('/api/v1/audio/transcribe',files={'file':('test.webm',content,mime)})
    assert result.status_code==status
    service.assert_not_called()


def test_resume_upload_read_is_bounded():
    upload = AsyncMock()
    upload.filename = 'test.pdf'
    upload.read.return_value = b'x' * (resume.MAX_FILE_SIZE_BYTES + 1)
    with pytest.raises(HTTPException) as err:
        asyncio.run(resume.parse_resume(upload))
    assert err.value.status_code == 413
    upload.read.assert_awaited_once_with(resume.MAX_FILE_SIZE_BYTES + 1)


def test_docx_expansion_guard():
    buf = BytesIO()
    with ZipFile(buf, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', b'x' * (51 * 1024 * 1024))
    with pytest.raises(FileTooLargeError): parse_resume_file('test.docx', buf.getvalue())


def test_actual_application_cors_and_size_guard():
    from app.main import app
    response = TestClient(app).post('/api/v1/resume/parse', headers={'Origin':'http://127.0.0.1:5173','Content-Length': str(12*1024*1024)})
    assert response.status_code == 413
    assert response.headers['access-control-allow-origin']=='http://127.0.0.1:5173'


def test_legacy_introduction_alias_is_preserved():
    request = AdaptiveNextQuestionRequest(previous_question='Introduce yourself',candidate_answer='I study computer science',evaluation={'score':70},category='Introduction')
    assert request.category == 'Technical'
    assert AnswerEvaluationRequest(question='Introduce yourself',candidate_answer='I study computer science',category='Introduction',stage='INTRO').category=='Technical'


def test_start_rejects_foreign_resume_before_generation():
    from types import SimpleNamespace
    with patch.object(interview,'read_owned_rows',AsyncMock(return_value=[])) as read, patch.object(interview,'process_adaptive_start',AsyncMock()) as generate:
        with pytest.raises(HTTPException) as err:
            asyncio.run(interview.start_interview(InterviewStartRequest(resume_id='foreign-resume'),SimpleNamespace(token='caller-jwt',user_id='owner')))
    assert err.value.status_code==404
    assert read.call_args.args == ('caller-jwt','resumes',{'id':'foreign-resume','user_id':'owner'})
    generate.assert_not_awaited()


@pytest.mark.parametrize('data', [{'sessionId':[]},{'sessionId':'s&other=1'},{'sessionId':'s','duration_secs':float('nan')},{'sessionId':'s','duration_secs':-1}])
def test_report_request_invalid_values(data):
    with pytest.raises(HTTPException) as err:
        asyncio.run(interview.save_interview_report(data, None))
    assert err.value.status_code==422


def test_report_persistence_failure_does_not_return_success():
    from types import SimpleNamespace
    session={'id':'db','role':'Engineer','interview_type':'Technical','difficulty':'Medium'}
    with patch.object(interview,'read_owned_rows',AsyncMock(side_effect=[[session],[],[]])), patch.object(interview,'persist_interview_report',AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as err:
            asyncio.run(interview._save_owned_report({'sessionId':'session'},SimpleNamespace(token='caller',user_id='owner')))
    assert err.value.status_code==503


@pytest.mark.parametrize('failure,status', [(httpx.ConnectError(SECRET),503),(httpx.ReadTimeout(SECRET),504)])
def test_database_transport_failure_response(failure,status,caplog):
    app=test_app()
    @app.get('/database')
    def database(): raise failure
    response=TestClient(app).get('/database')
    assert response.status_code==status
    assert SECRET not in response.text+caplog.text
