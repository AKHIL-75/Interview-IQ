"""Offline coverage: no Azure calls, real credentials, or quota usage."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.endpoints import speech
from app.core.auth import AuthUser, get_current_auth
from app.core.config import settings
from app.core.exceptions import install_exception_handlers
from app.core.request_limits import RequestLimitsMiddleware, LocalRateLimiter
from app.services.tts_service import SpeechService, SpeechTimeoutError, SpeechSynthesisError, SpeechUnavailableError

VOICES = ['en-IN-NeerjaNeural', 'en-IN-PrabhatNeural', 'en-IN-AaravNeural',
          'en-US-JennyNeural', 'en-US-BrianNeural']


@pytest.mark.parametrize('voice', VOICES)
def test_each_selected_voice_reaches_azure(voice):
    sdk, synth = fake_sdk()
    with patch('app.services.tts_service.importlib.import_module', return_value=sdk):
        response = client().post('/api/v1/speech/synthesize', json={'text': 'Question', 'voice': voice})
    assert response.status_code == 200
    assert response.headers['content-type'] == 'audio/mpeg'
    assert response.content == b'ID3-mock-audio'
    assert sdk.SpeechConfig.return_value.speech_synthesis_voice_name == voice
    synth.speak_text_async.assert_called_once_with('Question')


def test_service_rejects_unknown_voice_without_loading_sdk():
    with patch('app.services.tts_service.importlib.import_module') as load:
        with pytest.raises(SpeechSynthesisError):
            SpeechService().synthesize('Question', 'en-US-AriaNeural')
    load.assert_not_called()


@pytest.fixture(autouse=True)
def fake_configuration(monkeypatch):
    monkeypatch.setattr(settings, 'AZURE_SPEECH_KEY', SecretStr('mock-key'))
    monkeypatch.setattr(settings, 'AZURE_SPEECH_REGION', 'eastasia')


def client(auth=True, limit=30):
    app = FastAPI()
    install_exception_handlers(app)
    app.add_middleware(RequestLimitsMiddleware, limiter=LocalRateLimiter(limit=limit))
    app.include_router(speech.router, prefix='/api/v1/speech')
    if auth:
        app.dependency_overrides[get_current_auth] = lambda: AuthUser(uuid4(), 'mock-token')
    return TestClient(app)


def fake_sdk(reason='completed', audio=b'ID3-mock-audio', completes=True):
    result = SimpleNamespace(reason=reason, audio_data=audio)
    synthesizer = Mock()
    callbacks = {}
    synthesizer.synthesis_completed.connect.side_effect = lambda cb: callbacks.update(completed=cb)
    synthesizer.synthesis_canceled.connect.side_effect = lambda cb: callbacks.update(canceled=cb)

    def speak(text):
        if completes:
            callbacks['completed' if reason == 'completed' else 'canceled'](SimpleNamespace(result=result))
        return Mock(get=Mock(return_value=result))

    synthesizer.speak_text_async.side_effect = speak
    sdk = SimpleNamespace(
        SpeechConfig=Mock(), SpeechSynthesizer=Mock(return_value=synthesizer),
        SpeechSynthesisOutputFormat=SimpleNamespace(Audio16Khz32KBitRateMonoMp3='mp3'),
        ResultReason=SimpleNamespace(SynthesizingAudioCompleted='completed'),
    )
    return sdk, synthesizer


def test_auth_required_before_synthesis():
    with patch.object(speech.speech_service, 'synthesize') as synthesize:
        response = client(auth=False).post('/api/v1/speech/synthesize', json={'text': 'Question'})
    assert response.status_code == 401
    synthesize.assert_not_called()


def test_invalid_token_rejected():
    with patch('app.core.auth.httpx.AsyncClient') as http, patch.object(speech.speech_service, 'synthesize') as synthesize:
        from unittest.mock import AsyncMock
        http.return_value.__aenter__.return_value.get = AsyncMock(return_value=SimpleNamespace(status_code=401))
        with patch.object(settings, 'SUPABASE_URL', 'https://mock.invalid'), patch.object(settings, 'SUPABASE_ANON_KEY', 'mock'):
            response = client(auth=False).post('/api/v1/speech/synthesize', headers={'Authorization': 'Bearer invalid'}, json={'text': 'Question'})
    assert response.status_code == 401
    synthesize.assert_not_called()


@pytest.mark.parametrize('payload', [{}, {'text': ''}, {'text': '   '}, {'text': 'x' * 3001},
    {'text': 12}, {'text': 'Question', 'voice': 'unsupported'}, {'text': 'Question', 'key': 'private'}])
def test_validation_before_synthesis(payload):
    with patch.object(speech.speech_service, 'synthesize') as synthesize:
        response = client().post('/api/v1/speech/synthesize', json=payload)
    assert response.status_code == 422
    assert 'private' not in response.text
    synthesize.assert_not_called()


def test_returns_mp3_with_trimmed_text():
    sdk, synth = fake_sdk()
    with patch('app.services.tts_service.importlib.import_module', return_value=sdk):
        response = client().post('/api/v1/speech/synthesize', json={'text': '  Explain a queue.  '})
    assert response.status_code == 200
    assert response.content == b'ID3-mock-audio'
    assert response.headers['content-type'] == 'audio/mpeg'
    assert response.headers['cache-control'] == 'no-store'
    synth.speak_text_async.assert_called_once_with('Explain a queue.')
    sdk.SpeechConfig.assert_called_once_with(subscription='mock-key', region='eastasia')
    assert sdk.SpeechConfig.return_value.speech_synthesis_voice_name == 'en-US-JennyNeural'
    sdk.SpeechConfig.return_value.set_speech_synthesis_output_format.assert_called_once_with('mp3')
    assert sdk.SpeechSynthesizer.call_args.kwargs['audio_config'] is None


@pytest.mark.parametrize('field,value', [('AZURE_SPEECH_KEY', SecretStr('')), ('AZURE_SPEECH_REGION', '')])
def test_missing_config_keeps_service_optional(monkeypatch, field, value):
    monkeypatch.setattr(settings, field, value)
    with patch('app.services.tts_service.importlib.import_module') as load:
        response = client().post('/api/v1/speech/synthesize', json={'text': 'Question'})
    assert response.status_code == 503
    load.assert_not_called()


@pytest.mark.parametrize('failure,status', [(SpeechUnavailableError(), 503), (SpeechSynthesisError(), 502), (SpeechTimeoutError(), 504)])
def test_safe_service_errors(failure, status, caplog):
    with patch.object(speech.speech_service, 'synthesize', side_effect=failure):
        response = client().post('/api/v1/speech/synthesize', json={'text': 'Private question'})
    assert response.status_code == status
    assert 'mock-key' not in response.text + caplog.text
    assert 'Private question' not in response.text + caplog.text


@pytest.mark.parametrize('reason,audio', [('canceled', b''), ('completed', b'')])
def test_canceled_or_empty_output(reason, audio):
    sdk, _ = fake_sdk(reason, audio)
    with patch('app.services.tts_service.importlib.import_module', return_value=sdk), pytest.raises(SpeechSynthesisError):
        SpeechService().synthesize('Question')


def test_timeout_stops_sdk_and_releases_capacity():
    sdk, synth = fake_sdk(completes=False)
    service = SpeechService(timeout=0.001)
    with patch('app.services.tts_service.importlib.import_module', return_value=sdk):
        for _ in range(3):
            with pytest.raises(SpeechTimeoutError):
                service.synthesize('Question')
    assert synth.stop_speaking_async.call_count == 3
    assert synth.synthesis_completed.disconnect_all.call_count == 3


def test_missing_sdk_and_sensitive_sdk_failure(caplog):
    with patch('app.services.tts_service.importlib.import_module', side_effect=ImportError()):
        assert client().post('/api/v1/speech/synthesize', json={'text': 'Question'}).status_code == 503
    sdk, _ = fake_sdk()
    sdk.SpeechConfig.side_effect = RuntimeError('mock-key private-diagnostics')
    with patch('app.services.tts_service.importlib.import_module', return_value=sdk):
        response = client().post('/api/v1/speech/synthesize', json={'text': 'Question'})
    assert response.status_code == 502
    assert 'mock-key' not in response.text + caplog.text
    assert 'private-diagnostics' not in response.text + caplog.text


def test_capacity_and_rate_limit():
    service = SpeechService()
    service._slots.acquire()
    service._slots.acquire()
    with pytest.raises(SpeechUnavailableError):
        service.synthesize('Question')
    with patch.object(speech.speech_service, 'synthesize', return_value=b'ID3') as synthesize:
        http = client(limit=1)
        assert http.post('/api/v1/speech/synthesize', json={'text': 'Question'}).status_code == 200
        assert http.post('/api/v1/speech/synthesize', json={'text': 'Question'}).status_code == 429
    assert synthesize.call_count == 1
