"""Azure-only upload contracts with a mocked SDK and real PyAV decoding."""
import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import math
import os
import struct
import tempfile
import wave
from pathlib import Path
import pytest
from tests.test_azure_stt import isolated, fake_sdk, upload, provider, azure, assert_released
from app.services.audio_diagnostics import inspect_audio

def generate_test_wav(duration_s=1.0, sample_rate=16000, frequency=440.0) -> bytes:
    """Generate a valid PCM 16-bit mono WAV in memory."""
    num_samples = int(duration_s * sample_rate)
    wav_io = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav_path = wav_io.name
    wav_io.close()

    try:
        with wave.open(wav_path, "w") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)

            # Generate sine wave with slight amplitude modulation
            frames = bytearray()
            for i in range(num_samples):
                t = i / sample_rate
                val = int(32767.0 * 0.5 * math.sin(2.0 * math.pi * frequency * t))
                frames.extend(struct.pack("<h", val))

            wav_file.writeframes(frames)

        with open(wav_path, "rb") as f:
            data = f.read()
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)

    return data



def test_azure_provider_reuses_bounded_service(monkeypatch):
    fake_sdk(monkeypatch)
    assert upload().status_code == 200
    first = provider._azure
    fake_sdk(monkeypatch)
    assert upload().status_code == 200
    assert provider._azure is first


def test_stt_transcribe_audio_file(monkeypatch):
    fake = fake_sdk(monkeypatch, result="Quartz Harbor, violet comet 47.")
    monkeypatch.setattr(azure, "inspect_audio", inspect_audio)
    response = upload(content=generate_test_wav(2), mime="audio/wav")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] and data["text"] == "Quartz Harbor, violet comet 47."
    assert data["model"] == "azure-stt:en-IN" and data["language"] == "en-IN"
    assert data["duration_seconds"] == pytest.approx(2)
    assert data["processing_time_ms"] >= 0
    assert_released(fake)


def test_audio_endpoint_valid_wav(monkeypatch):
    fake_sdk(monkeypatch)
    monkeypatch.setattr(azure, "inspect_audio", inspect_audio)
    result = upload(content=generate_test_wav(1.5), mime="audio/wav")
    assert result.status_code == 200
    assert result.json()["duration_seconds"] == pytest.approx(1.5)


@pytest.mark.parametrize("content,mime,status", [(b"", "audio/wav", 400), (b"plain text", "text/plain", 415)])
def test_audio_upload_validation_before_sdk(monkeypatch, content, mime, status):
    fake = fake_sdk(monkeypatch)
    response = upload(content=content, mime=mime)
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == status
    assert isinstance(response.json()["detail"], str)
    fake.sdk.SpeechRecognizer.assert_not_called()


def test_corrupt_audio_rejected_before_sdk(monkeypatch):
    fake = fake_sdk(monkeypatch)
    monkeypatch.setattr(azure, "inspect_audio", inspect_audio)
    assert upload(content=b"corrupt", mime="audio/wav").status_code == 422
    fake.sdk.SpeechRecognizer.assert_not_called()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
