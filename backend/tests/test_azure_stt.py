"""Offline Azure STT coverage. All fake adapters and credentials are test-local."""
import asyncio
import builtins
import importlib
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.api.v1.endpoints import audio, speech_stt
from app.core.auth import AuthUser, get_current_auth
from app.core.config import Settings, settings
from app.core.exceptions import install_exception_handlers
from app.core.request_limits import LocalRateLimiter, RequestLimitsMiddleware
from app.services import azure_stt_service as azure, stt_provider as provider
from app.services.stt_service import TranscriptionError


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    original = builtins.__import__
    def guard(name, *args, **kwargs):
        assert not name.startswith(("faster_whisper", "sherpa_onnx")), "Retired ASR dependency"
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guard)
    for name, value in {
        "AZURE_STT_SPEECH_KEY": SecretStr("synthetic-stt-secret"),
        "AZURE_STT_SPEECH_REGION": "centralindia", "AZURE_STT_ENDPOINT": "",
        "AZURE_STT_LANGUAGE": "en-IN", "AZURE_STT_TIMEOUT_S": 630,
        "AZURE_STT_MAX_AUDIO_S": 600, "AZURE_STT_MAX_CONCURRENCY": 1,
        "AZURE_STT_PHRASE_LIST": "",
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(provider, "_azure", None)
    provider.start_stt()
    yield
    provider.shutdown_stt()
    provider.start_stt()


def client(auth=True, limit=100):
    app = FastAPI()
    install_exception_handlers(app)
    app.add_middleware(RequestLimitsMiddleware, limiter=LocalRateLimiter(limit=limit))
    app.include_router(audio.router, prefix="/api/v1/audio")
    app.include_router(speech_stt.router, prefix="/api/v1/speech")
    if auth:
        app.dependency_overrides[get_current_auth] = lambda: AuthUser(uuid4(), "synthetic-auth")
    return TestClient(app)


def upload(http=None, content=b"fixture", mime="audio/webm", vad=None):
    return (http or client()).post("/api/v1/audio/transcribe", files={"file": ("answer.webm", content, mime)},
                                 data={} if vad is None else {"vad_filter": str(vad).lower()})




def request_stub():
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
    async def receive():
        while not await request.is_disconnected():
            await asyncio.sleep(.001)
        return {"type": "http.disconnect"}
    request.receive = receive
    return request


class Signal:
    def __init__(self):
        self.handlers = []
    def connect(self, callback):
        self.handlers.append(callback)
    def disconnect_all(self):
        self.handlers.clear()
    def emit(self, event=None):
        for callback in list(self.handlers):
            callback(event)


def fake_sdk(monkeypatch, *, result="spoken answer", reason=None, code="ServiceError", stalled=False, duration=2):
    config = SimpleNamespace()
    recognizer = SimpleNamespace(recognized=Signal(), canceled=Signal(), session_stopped=Signal())
    started = threading.Event()
    stream = SimpleNamespace(chunks=[], closed=False)
    completed = False
    def close():
        nonlocal completed
        stream.closed = True
        if completed or stalled:
            return
        completed = True
        if reason:
            recognizer.canceled.emit(SimpleNamespace(cancellation_details=SimpleNamespace(reason=reason, code=code, error_details="synthetic-stt-secret")))
        elif result is not None:
            recognizer.recognized.emit(SimpleNamespace(result=SimpleNamespace(reason="RecognizedSpeech", text=result)))
        recognizer.session_stopped.emit()
    stream.write = Mock(side_effect=lambda data: stream.chunks.append(data))
    stream.close = Mock(side_effect=close)
    recognizer.start_continuous_recognition_async = Mock(side_effect=lambda: (started.set(), Mock())[1])
    recognizer.stop_continuous_recognition_async = Mock(return_value=Mock())
    sdk = SimpleNamespace(
        SpeechConfig=Mock(return_value=config), SpeechRecognizer=Mock(return_value=recognizer),
        audio=SimpleNamespace(PushAudioInputStream=Mock(return_value=stream), AudioStreamFormat=Mock(), AudioConfig=Mock()),
        PhraseListGrammar=SimpleNamespace(from_recognizer=Mock(return_value=SimpleNamespace(addPhrase=Mock()))),
        ResultReason=SimpleNamespace(RecognizedSpeech="RecognizedSpeech"),
        CancellationReason=SimpleNamespace(Error="Error", EndOfStream="EndOfStream", CancelledByUser="CancelledByUser"),
        CancellationErrorCode=SimpleNamespace(ServiceTimeout="ServiceTimeout"),
    )
    original_import = importlib.import_module
    monkeypatch.setattr(azure.importlib, "import_module", lambda name, *args, **kwargs: sdk if name == "azure.cognitiveservices.speech" else original_import(name, *args, **kwargs))
    stats = dict(duration_seconds=duration, rms_dbfs=-18, near_clip_fraction=0, quiet_frame_fraction=0)
    monkeypatch.setattr(azure, "inspect_audio", Mock(return_value=(np.array([0, .5, -1, 1], dtype=np.float32), stats)))
    return SimpleNamespace(sdk=sdk, config=config, recognizer=recognizer, stream=stream, started=started)


def assert_released(fake):
    assert fake.stream.closed
    assert not fake.recognizer.recognized.handlers
    assert not fake.recognizer.canceled.handlers
    assert not fake.recognizer.session_stopped.handlers
    fake.recognizer.stop_continuous_recognition_async.assert_called_once()
    assert provider._azure.slots.acquire(timeout=1)
    provider._azure.slots.release()


def test_defaults_and_invalid_settings():
    config = Settings(_env_file=None)
    assert not {"STT_PROVIDER", "STT_ENGINE", "WHISPER_MODEL", "PARAKEET_MODEL_DIR"} & config.model_fields.keys()
    assert config.AZURE_STT_TIMEOUT_S == 630 and config.AZURE_STT_MAX_AUDIO_S == 600
    for change in ({"AZURE_STT_TIMEOUT_S": 0}, {"AZURE_STT_MAX_CONCURRENCY": 0}):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **change)



def test_azure_success_pcm_contract_language_phrase_list_and_temp_cleanup(monkeypatch):
    fake = fake_sdk(monkeypatch)
    monkeypatch.setattr(settings, "AZURE_STT_PHRASE_LIST", " SQL, ,React ")
    created = []
    original = audio.tempfile.mkstemp
    def capture(**kwargs):
        result = original(**kwargs)
        created.append(Path(result[1]))
        return result
    monkeypatch.setattr(audio.tempfile, "mkstemp", capture)
    response = upload(vad=False)
    assert response.status_code == 200
    assert set(response.json()) == set(audio.TranscriptionResponse.model_fields)
    assert response.json()["model"] == "azure-stt:en-IN"
    assert response.json()["text"] == "spoken answer"
    assert fake.config.speech_recognition_language == "en-IN"
    assert np.frombuffer(b"".join(fake.stream.chunks), dtype="<i2").tolist() == [0, 16384, -32768, 32767]
    fake.sdk.audio.AudioStreamFormat.assert_called_once_with(samples_per_second=16000, bits_per_sample=16, channels=1)
    assert [call.args[0] for call in fake.sdk.PhraseListGrammar.from_recognizer.return_value.addPhrase.call_args_list] == ["SQL", "React"]
    assert created and all(not path.exists() for path in created)
    assert_released(fake)


@pytest.mark.parametrize("code", ["AuthenticationFailure", "Forbidden", "TooManyRequests", "ConnectionFailure", "ServiceTimeout", "ServiceError", "ServiceUnavailable", "RuntimeError"])
def test_provider_error_codes_route_safely(monkeypatch, code):
    fake = fake_sdk(monkeypatch, reason="Error", code=code)
    response = upload(vad=False)
    assert response.status_code == (504 if code == "ServiceTimeout" else 422)
    assert set(response.json()) == {"type", "title", "status", "detail", "request_id"}
    assert_released(fake)


@pytest.mark.parametrize("field,value", [("AZURE_STT_SPEECH_KEY", SecretStr("")), ("AZURE_STT_SPEECH_REGION", ""), ("AZURE_STT_SPEECH_REGION", "CentralIndia")])
def test_missing_invalid_config_routes_safely(monkeypatch, field, value):
    fake_sdk(monkeypatch)
    monkeypatch.setattr(settings, field, value)
    response = upload()
    assert response.status_code == 503


def test_hard_timeout_releases_resources(monkeypatch):
    fake = fake_sdk(monkeypatch, stalled=True)
    monkeypatch.setattr(settings, "AZURE_STT_TIMEOUT_S", .1)
    response = upload()
    assert response.status_code == 504
    assert_released(fake)


@pytest.mark.parametrize("result,reason", [("", None), (None, "EndOfStream")])
def test_empty_even_loud_audio_and_end_of_stream_do_not_fall_back(monkeypatch, result, reason):
    fake = fake_sdk(monkeypatch, result=result, reason=reason, code="NoError")
    response = upload()
    assert response.status_code == 200 and response.json()["text"] == ""
    assert_released(fake)


@pytest.mark.parametrize("content,mime,status", [(b"", "audio/webm", 400), (b"x", "image/png", 415)])
def test_validation_never_invokes_a_provider(monkeypatch, content, mime, status):
    routed = Mock(side_effect=AssertionError("must not route"))
    monkeypatch.setattr(provider, "transcribe_with_provider", routed)
    assert upload(content=content, mime=mime).status_code == status
    routed.assert_not_called()


def test_corrupt_and_overlong_audio_never_fall_back(monkeypatch):
    fake_sdk(monkeypatch, duration=601)
    assert upload().status_code == 422
    monkeypatch.setattr(azure, "inspect_audio", Mock(side_effect=ValueError("bad format")))
    assert upload().status_code == 422



def test_duration_timeout_formula(monkeypatch):
    assert [azure.effective_timeout(value) for value in [0, 30, 120, 600, 900]] == [30, 60, 150, 630, 630]
    monkeypatch.setattr(settings, "AZURE_STT_TIMEOUT_S", 80)
    assert azure.effective_timeout(120) == 80


@pytest.mark.parametrize("action", ["cancel", "disconnect", "shutdown", "own_stop", "sdk_user_cancel"])
def test_cancellation_never_falls_back_and_releases_everything(monkeypatch, action):
    fake = fake_sdk(monkeypatch, stalled=True)
    disconnected = False
    async def is_disconnected():
        return disconnected
    request = request_stub()
    request.is_disconnected = is_disconnected
    async def exercise():
        nonlocal disconnected
        task = asyncio.create_task(provider.transcribe_with_provider("test", None, request))
        while not fake.started.is_set():
            await asyncio.sleep(.001)
        if action == "cancel": task.cancel()
        elif action == "disconnect": disconnected = True
        elif action == "shutdown": provider.shutdown_stt()
        elif action == "own_stop": next(iter(provider._active)).set()
        else: fake.recognizer.canceled.emit(SimpleNamespace(cancellation_details=SimpleNamespace(reason="CancelledByUser", code="NoError")))
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
    asyncio.run(exercise())
    assert not provider._active
    assert_released(fake)


def test_cancel_after_provider_failure_prevents_fallback(monkeypatch):
    def fail(path, stop, **kwargs):
        stop.set()
        raise azure.AzureSTTError()
    monkeypatch.setattr(provider, "_azure", SimpleNamespace(transcribe=fail))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(provider.transcribe_with_provider("test", None, request_stub()))


def test_shutdown_rejects_new_work(monkeypatch):
    provider.shutdown_stt()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(provider.transcribe_with_provider("test", None, request_stub()))



def upstream(monkeypatch, status=200, text="synthetic-token"):
    http = Mock()
    http.return_value.__aenter__ = AsyncMock(return_value=SimpleNamespace(post=AsyncMock(return_value=SimpleNamespace(status_code=status, text=text))))
    http.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(speech_stt.httpx, "AsyncClient", http)
    return http.return_value.__aenter__.return_value.post


@pytest.mark.parametrize("endpoint", ["", "https://stt-test.cognitiveservices.azure.com"])
def test_token_exact_response_and_stt_resource_headers(monkeypatch, endpoint):
    monkeypatch.setattr(settings, "AZURE_STT_ENDPOINT", endpoint)
    post = upstream(monkeypatch)
    response = client().post("/api/v1/speech/stt-token")
    assert response.status_code == 200
    assert response.json() == dict(token="synthetic-token", region="centralindia", expires_in_s=600)
    assert response.headers["cache-control"] == "no-store"
    assert post.call_args.args == ((endpoint or "https://centralindia.api.cognitive.microsoft.com") + "/sts/v1.0/issueToken",)
    assert post.call_args.kwargs["headers"]["Ocp-Apim-Subscription-Key"] == "synthetic-stt-secret"


@pytest.mark.parametrize("route", ["/stt-token", "/stt-config"])
def test_token_and_config_require_auth(monkeypatch, route):
    post = upstream(monkeypatch)
    http = client(auth=False)
    response = http.post("/api/v1/speech" + route) if route == "/stt-token" else http.get("/api/v1/speech" + route)
    assert response.status_code == 401
    post.assert_not_called()


def test_invalid_auth_no_token_request(monkeypatch):
    post = upstream(monkeypatch)
    # Shared httpx module is mocked at the actual Supabase validation boundary.
    speech_stt.httpx.AsyncClient.return_value.__aenter__.return_value.get = AsyncMock(return_value=SimpleNamespace(status_code=401))
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://auth.invalid")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "synthetic-auth-key")
    response = client(auth=False).post("/api/v1/speech/stt-token", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    post.assert_not_called()


@pytest.mark.parametrize("field,value", [("AZURE_STT_SPEECH_KEY", SecretStr("")), ("AZURE_STT_SPEECH_REGION", ""),
    ("AZURE_STT_ENDPOINT", "https://attacker.invalid"), ("AZURE_STT_ENDPOINT", "https://host.cognitiveservices.azure.com/path?language=fr"),
    ("AZURE_STT_ENDPOINT", "https://user:password@host.cognitiveservices.azure.com"), ("AZURE_STT_ENDPOINT", "http://host.cognitiveservices.azure.com")])
def test_unconfigured_invalid_endpoint_never_request_tokens(monkeypatch, field, value):
    monkeypatch.setattr(settings, field, value)
    post = upstream(monkeypatch)
    assert client().post("/api/v1/speech/stt-token").status_code == 503
    response = client().get("/api/v1/speech/stt-config")
    assert response.json() == {"enabled": False, "language": "en-IN"}
    post.assert_not_called()


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500, 503])
def test_token_provider_failures_sanitized(monkeypatch, status, caplog):
    upstream(monkeypatch, status, "synthetic-stt-secret synthetic-token private-transcript")
    response = client().post("/api/v1/speech/stt-token")
    assert response.status_code in {502, 503}
    for secret in ["synthetic-stt-secret", "synthetic-token", "private-transcript"]:
        assert secret not in response.text + caplog.text
    assert set(response.json()) == {"type", "title", "status", "detail", "request_id"}


def test_token_network_error_rate_limit_and_config(monkeypatch):
    import httpx
    post = upstream(monkeypatch)
    post.side_effect = httpx.ConnectError("synthetic-stt-secret")
    assert client().post("/api/v1/speech/stt-token").status_code == 503
    post.side_effect = None
    http = client(limit=1)
    assert http.post("/api/v1/speech/stt-token").status_code == 200
    response = http.post("/api/v1/speech/stt-token")
    assert response.status_code == 429 and "retry-after" in response.headers
    monkeypatch.setattr(settings, "AZURE_STT_ENDPOINT", "https://stt-test.cognitiveservices.azure.com")
    config = http.get("/api/v1/speech/stt-config")
    assert config.json() == dict(enabled=True, language="en-IN", endpoint="https://stt-test.cognitiveservices.azure.com")
    assert config.headers["cache-control"] == "no-store"


def test_no_sensitive_content_in_success_or_failure_logs(monkeypatch, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    fake_sdk(monkeypatch, result="private-transcript")
    assert upload().status_code == 200
    upstream(monkeypatch)
    assert client().post("/api/v1/speech/stt-token").status_code == 200
    for value in ["private-transcript", "synthetic-stt-secret", "synthetic-token"]:
        assert value not in caplog.text


def test_installed_sdk_cancellation_contract_matches_adapter():
    from azure.cognitiveservices.speech import CancellationDetails, CancellationErrorCode
    assert isinstance(CancellationDetails.code, property)
    assert isinstance(CancellationDetails.reason, property)
    assert CancellationErrorCode.ServiceTimeout.name == "ServiceTimeout"


@pytest.mark.parametrize("failure", ["missing_sdk", "connection"])
def test_sdk_import_and_initialization_failures_sanitized(monkeypatch, failure, caplog):
    fake = fake_sdk(monkeypatch)
    if failure == "missing_sdk":
        monkeypatch.setattr(azure.importlib, "import_module", Mock(side_effect=ImportError("synthetic-stt-secret")))
    else:
        fake.sdk.SpeechRecognizer.side_effect = RuntimeError("synthetic-stt-secret private-transcript")
    response = upload()
    assert response.status_code == (503 if failure == "missing_sdk" else 422)
    assert "synthetic-stt-secret" not in response.text + caplog.text
    assert "private-transcript" not in response.text + caplog.text
    assert provider._azure.slots.acquire(timeout=1)
    provider._azure.slots.release()


def test_upload_size_validation_unchanged(monkeypatch):
    monkeypatch.setattr(audio, "MAX_AUDIO_SIZE_BYTES", 3)
    assert upload(content=b"four").status_code == 413
    assert provider._azure is None


@pytest.mark.parametrize("format", ["wav", "webm"])
def test_actual_decoder_feeds_only_pcm_to_mock_azure(monkeypatch, tmp_path, format):
    from app.services.audio_diagnostics import inspect_audio
    from tests.test_stt_speech import opus_file
    source = Path(__file__).parent / "fixtures" / "synthetic_candidate.wav"
    if format == "webm":
        source = tmp_path / "recording.webm"
        opus_file(source)
    fake = fake_sdk(monkeypatch)
    monkeypatch.setattr(azure, "inspect_audio", inspect_audio)
    response = upload(content=source.read_bytes(), mime="audio/" + format)
    assert response.status_code == 200
    assert 33 < response.json()["duration_seconds"] < 35
    assert response.json()["audio"]["decoded_sample_rate"] == 16000
    samples, _ = inspect_audio(source)
    expected = np.clip(samples * 32768, -32768, 32767).astype("<i2").tobytes()
    assert b"".join(fake.stream.chunks) == expected
    assert all(len(chunk) <= 32000 for chunk in fake.stream.chunks)
    assert_released(fake)


def test_native_cleanup_is_bounded_and_retains_concurrency_slot(monkeypatch):
    fake = fake_sdk(monkeypatch, stalled=True)
    # Expire only after SDK startup: a deadline that expires before startup
    # correctly has no native cleanup handle or occupied slot to retain.
    monkeypatch.setattr(settings, "AZURE_STT_TIMEOUT_S", 30)
    real_clock = time.monotonic
    native_started = []
    def clock():
        return real_clock() + (31 if native_started else 0)
    def start_native():
        native_started.append(real_clock())
        fake.started.set()
        return Mock()
    monkeypatch.setattr(azure, "time", SimpleNamespace(monotonic=clock))
    fake.recognizer.start_continuous_recognition_async.side_effect = start_native
    release = threading.Event()
    future = Mock()
    future.get.side_effect = lambda: release.wait(2)
    fake.recognizer.stop_continuous_recognition_async.return_value = future
    try:
        assert upload().status_code == 504
        assert native_started
        assert real_clock() - native_started[0] < 1
        assert not provider._azure.slots.acquire(blocking=False)
        assert fake.stream.closed
    finally:
        release.set()
    assert_released(fake)
    future.get.assert_called_once()


def test_concurrency_limit_and_queued_cancellation(monkeypatch):
    fake = fake_sdk(monkeypatch, stalled=True)
    request = request_stub()
    async def exercise():
        first = asyncio.create_task(provider.transcribe_with_provider("first", None, request))
        while not fake.started.is_set():
            await asyncio.sleep(.001)
        second = asyncio.create_task(provider.transcribe_with_provider("second", None, request))
        await asyncio.sleep(.1)
        fake.sdk.SpeechRecognizer.assert_called_once()
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(second, 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first, 1)
    asyncio.run(exercise())
    assert_released(fake)


def test_shutdown_between_scheduling_and_worker_invocation_skips_fallback(monkeypatch):
    fake_sdk(monkeypatch, reason="Error")
    original = asyncio.to_thread
    calls = 0
    async def queued(function, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            provider.shutdown_stt()
        return await original(function, *args, **kwargs)
    monkeypatch.setattr(asyncio, "to_thread", queued)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(provider.transcribe_with_provider("test", None, request_stub()))
    assert calls == 1


def test_partial_text_discarded_on_disconnect_and_temp_file_removed(monkeypatch):
    import io
    from starlette.datastructures import UploadFile, Headers
    fake = fake_sdk(monkeypatch, stalled=True)
    request = request_stub()
    async def exercise():
        file = UploadFile(io.BytesIO(b"fixture"), filename="test.wav", headers=Headers({"content-type": "audio/wav"}))
        task = asyncio.create_task(audio.transcribe_audio(request, file, None))
        while not fake.started.is_set():
            await asyncio.sleep(.001)
        path = azure.inspect_audio.call_args.args[0]
        fake.recognizer.recognized.emit(SimpleNamespace(result=SimpleNamespace(reason="RecognizedSpeech", text="private-partial")))
        request.is_disconnected.return_value = True
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert not Path(path).exists()
    asyncio.run(exercise())
    assert_released(fake)


def test_router_lifecycle_closes_and_reopens_stt():
    with client():
        assert not provider._closing.is_set()
    assert provider._closing.is_set()
    with client():
        assert not provider._closing.is_set()


@pytest.mark.parametrize("body", ["", "token with spaces", "x" * 16385], ids=["empty", "whitespace", "oversized"])
def test_invalid_token_response_is_sanitized(monkeypatch, body):
    upstream(monkeypatch, text=body)
    response = client().post("/api/v1/speech/stt-token")
    assert response.status_code == 502
    assert response.json()["detail"] == "The processing service returned an invalid response. Please retry."


def test_asgi_disconnect_through_real_middleware_never_falls_back(monkeypatch):
    from app.main import app
    monkeypatch.setitem(app.dependency_overrides, get_current_auth, lambda: AuthUser(uuid4(), "synthetic-auth"))
    monkeypatch.setattr(settings, "AZURE_STT_TIMEOUT_S", .3)
    fake = fake_sdk(monkeypatch, stalled=True)
    body = (b'--test\r\nContent-Disposition: form-data; name="file"; filename="test.wav"\r\n'
            b'Content-Type: audio/wav\r\n\r\nfixture\r\n--test--\r\n')
    scope = dict(type="http", asgi={"version": "3.0"}, http_version="1.1", method="POST", scheme="http",
                 path="/api/v1/audio/transcribe", raw_path=b"/api/v1/audio/transcribe", query_string=b"",
                 root_path="", headers=[(b"content-type", b"multipart/form-data; boundary=test")],
                 client=("192.0.2.42", 1234), server=("testserver", 80))
    async def exercise():
        messages = asyncio.Queue()
        await messages.put({"type": "http.request", "body": body, "more_body": False})
        sent = []
        async def send(message):
            sent.append(message)
        task = asyncio.create_task(app(scope, messages.get, send))
        while not fake.started.is_set():
            if task.done():
                await task
                pytest.fail("Recognition did not start")
            await asyncio.sleep(.001)
        await messages.put({"type": "http.disconnect"})
        try:
            await asyncio.wait_for(task, 1)
        except asyncio.CancelledError:
            pass
        assert not any(b"local answer" in message.get("body", b"") for message in sent)
    asyncio.run(exercise())
    assert_released(fake)
