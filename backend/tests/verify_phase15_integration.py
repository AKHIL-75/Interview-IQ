"""Offline Azure upload -> real evaluator pipeline; only external services mocked."""
import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
from app.main import app
from tests.test_azure_stt import isolated, fake_sdk, upload, azure, provider
from tests.test_phase15_stt import generate_test_wav
from app.services.audio_diagnostics import inspect_audio
from app.services import evaluator

ANSWER = "At Quartz Harbor I used binary search; violet comet 47."


def test_voice_pipeline_flow(monkeypatch):
    fake_sdk(monkeypatch, result=ANSWER)
    monkeypatch.setattr(azure, "inspect_audio", inspect_audio)
    response = upload(content=generate_test_wav(), mime="audio/wav")
    assert response.status_code == 200
    assert response.json()["text"] == ANSWER
    observed = []
    async def generate(prompt, **kwargs):
        observed.append(prompt)
        assert ANSWER in prompt
        return dict(technicalAccuracy=70, relevance=80, depth=60, clarity=80, answer_status="PARTIAL",
                    strengths=["Clear algorithm"], improvements=["Explain complexity"],
                    suggestedAnswer="A deliberately different reference answer.")
    monkeypatch.setattr(evaluator.llm_service, "generate_json_response", generate)
    result = TestClient(app).post("/api/v1/evaluation/evaluate", json={
        "question": "How would you search an ordered array efficiently?",
        "candidate_answer": response.json()["text"], "difficulty": "Medium",
        "topic": "Algorithms", "job_title": "Software Engineer"})
    assert result.status_code == 200
    assert observed and {"score", "strengths", "improvements", "technicalAccuracy"} <= result.json().keys()


@pytest.mark.parametrize("content,mime,status", [(b"", "audio/wav", 400), (b"test", "application/x-msdownload", 415)])
def test_edge_cases_and_cleanup(monkeypatch, content, mime, status):
    from app.api.v1.endpoints import audio
    from pathlib import Path
    created = []
    original = audio.tempfile.mkstemp
    def capture(**kwargs):
        fd, path = original(**kwargs); created.append(Path(path)); return fd, path
    monkeypatch.setattr(audio.tempfile, "mkstemp", capture)
    fake = fake_sdk(monkeypatch)
    assert upload(content=content, mime=mime).status_code == status
    assert all(not path.exists() for path in created)
    fake.sdk.SpeechRecognizer.assert_not_called()


@pytest.mark.parametrize("frequency", [0, 440])
def test_silence_and_non_speech_remain_empty(monkeypatch, frequency):
    fake_sdk(monkeypatch, result="")
    monkeypatch.setattr(azure, "inspect_audio", inspect_audio)
    result = upload(content=generate_test_wav(frequency=frequency), mime="audio/wav")
    assert result.status_code == 200 and result.json()["text"] == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
