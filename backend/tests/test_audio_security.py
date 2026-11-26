"""Audio-route security; all credentials and external responses are synthetic."""
from uuid import uuid4
from unittest.mock import Mock
import httpx
import pytest
from fastapi.testclient import TestClient
from app.core import auth
from app.core.config import settings
from app.api.v1.endpoints import audio
from app.main import app as full_application
from tests.test_azure_stt import isolated, fake_sdk, client, azure, provider


def application(monkeypatch, full_app):
    if not full_app:
        return client(auth=False)
    app = full_application
    monkeypatch.setattr(app, "dependency_overrides", {})
    monkeypatch.setattr(app, "middleware_stack", None)
    return TestClient(app)


def mock_auth(monkeypatch, accepted=False):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://auth.invalid")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "synthetic-anon")
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url.path == "/auth/v1/user"
        return httpx.Response(200, json={"id": str(uuid4())}) if accepted else httpx.Response(401, json={"message": "private-provider-detail"})
    actual_client = httpx.AsyncClient
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kwargs: actual_client(transport=httpx.MockTransport(handle), **kwargs))
    return calls


@pytest.mark.parametrize("full_app", [False, True], ids=["isolated", "full-app"])
@pytest.mark.parametrize("header", [None, "Basic malformed", "Bearer", "Bearer invalid", "Bearer expired"])
def test_unauthorized_audio_never_creates_route_tempfile_or_decodes(monkeypatch, caplog, full_app, header):
    calls = mock_auth(monkeypatch)
    fake = fake_sdk(monkeypatch)
    mkstemp = Mock(side_effect=AssertionError("Unauthorized route wrote audio"))
    monkeypatch.setattr(audio.tempfile, "mkstemp", mkstemp)
    import starlette.formparsers
    spool = Mock(side_effect=AssertionError("Unauthorized multipart parsing created a file"))
    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", spool)
    response = application(monkeypatch, full_app).post("/api/v1/audio/transcribe",
        files={"file": ("synthetic.wav", b"fixture", "audio/wav")},
        headers={} if header is None else {"Authorization": header})
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert "bearer" in response.headers["www-authenticate"].lower()
    assert len(calls) == int(bool(header and header.startswith("Bearer ")))
    mkstemp.assert_not_called()
    spool.assert_not_called()
    azure.inspect_audio.assert_not_called()
    fake.sdk.SpeechRecognizer.assert_not_called()
    assert provider._azure is None
    for value in ["Bearer invalid", "Bearer expired", "synthetic-anon", "private-provider-detail"]:
        assert value not in response.text + caplog.text


@pytest.mark.parametrize("full_app", [False, True], ids=["isolated", "full-app"])
def test_authenticated_audio_uses_real_auth_dependency_and_keeps_contract(monkeypatch, caplog, full_app):
    calls = mock_auth(monkeypatch, accepted=True)
    fake_sdk(monkeypatch, result="Quartz Harbor, violet comet 47.")
    response = application(monkeypatch, full_app).post("/api/v1/audio/transcribe",
        files={"file": ("synthetic.wav", b"fixture", "audio/wav")},
        headers={"Authorization": "Bearer synthetic-valid-auth"})
    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0].headers["authorization"] == "Bearer synthetic-valid-auth"
    assert response.json()["text"] == "Quartz Harbor, violet comet 47."
    assert response.json()["model"] == "azure-stt:en-IN"
    assert set(response.json()) == set(audio.TranscriptionResponse.model_fields)
    assert "synthetic-valid-auth" not in response.text + caplog.text


def test_auth_cache_is_request_scoped_and_not_reused_for_another_token(monkeypatch):
    calls = mock_auth(monkeypatch, accepted=True)
    http = application(monkeypatch, False)
    for token in ["synthetic-one", "synthetic-two"]:
        fake_sdk(monkeypatch)
        response = http.post("/api/v1/audio/transcribe", files={"file": ("test.wav", b"fixture", "audio/wav")},
                             headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200
    assert len(calls) == 2
    assert [call.headers["authorization"] for call in calls] == ["Bearer synthetic-one", "Bearer synthetic-two"]
