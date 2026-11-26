"""Real PyAV decoder coverage; speech recognition is explicitly mocked."""
from pathlib import Path
import numpy as np
import av
import pytest
from tests.test_azure_stt import isolated, fake_sdk, upload, azure
from app.services.audio_diagnostics import inspect_audio
FIXTURES = Path(__file__).parent / "fixtures"

def opus_file(target):
    # Re-encode the same synthetic speech to a browser-compatible WebM/Opus container.
    with av.open(str(FIXTURES/'synthetic_candidate.wav')) as source, av.open(str(target),'w',format='webm') as output:
        encoder=output.add_stream('libopus',rate=48000);encoder.layout='stereo';encoder.bit_rate=96000
        resampler=av.AudioResampler(format='s16',layout='stereo',rate=48000)
        for frame in source.decode(audio=0):
            for audio in resampler.resample(frame):
                for packet in encoder.encode(audio):output.mux(packet)
        for audio in resampler.resample(None):
            for packet in encoder.encode(audio):output.mux(packet)
        for packet in encoder.encode(None):output.mux(packet)

def test_wav_measurements_and_complete_duration():
    samples,stats=inspect_audio(FIXTURES/'synthetic_candidate.wav')
    assert stats['source_channels']==1 and stats['source_sample_rate']==22050
    assert stats['decoded_sample_rate']==16000 and samples.ndim==1
    assert 33 < stats['duration_seconds'] < 35
    assert -25 < stats['rms_dbfs'] < -15 and stats['near_clip_fraction']==0


def test_mock_speech_preserves_start_end_and_technical_terms(monkeypatch):
    expected = (FIXTURES / "speech_reference.txt").read_text().strip()
    fake_sdk(monkeypatch, result=expected)
    monkeypatch.setattr(azure, "inspect_audio", inspect_audio)
    response = upload(content=(FIXTURES / "synthetic_candidate.wav").read_bytes(), mime="audio/wav")
    assert response.status_code == 200 and response.json()["text"] == expected
    assert response.json()["language"] == "en-IN"
    assert response.json()["total_time_ms"] >= response.json()["processing_time_ms"]


def test_webm_opus_stereo_upload_and_temp_cleanup(tmp_path, monkeypatch):
    from app.api.v1.endpoints import audio
    webm = tmp_path / "candidate.webm"; opus_file(webm)
    _, stats = inspect_audio(webm)
    assert stats["codec"] == "opus" and stats["source_channels"] == 2
    assert stats["source_sample_rate"] == 48000 and 33 < stats["duration_seconds"] < 35
    created = []; original = audio.tempfile.mkstemp
    def capture(**kwargs):
        result = original(dir=tmp_path, **kwargs); created.append(Path(result[1])); return result
    monkeypatch.setattr(audio.tempfile, "mkstemp", capture)
    fake_sdk(monkeypatch, result="Python React SQL Git. Thank you for listening.")
    monkeypatch.setattr(azure, "inspect_audio", inspect_audio)
    response = upload(content=webm.read_bytes(), mime="audio/webm;codecs=opus")
    assert response.status_code == 200
    assert response.json()["text"] == "Python React SQL Git. Thank you for listening."
    assert response.json()["audio"]["codec"] == "opus"
    assert created and all(not path.exists() for path in created)


@pytest.mark.parametrize("content,status", [(b"not a recording", 422), (b"", 400)])
def test_corrupt_and_empty_audio_never_initializes_sdk(monkeypatch, content, status):
    fake = fake_sdk(monkeypatch)
    monkeypatch.setattr(azure, "inspect_audio", inspect_audio)
    assert upload(content=content).status_code == status
    fake.sdk.SpeechRecognizer.assert_not_called()


def test_uncertain_repetitive_speech_is_flagged_without_rewriting():
    from types import SimpleNamespace
    from app.services.stt_service import recognition_warnings
    raw='taxis ' * 20
    messages=recognition_warnings({'rms_dbfs':-29.27,'near_clip_fraction':0},[SimpleNamespace(avg_logprob=-1.2,compression_ratio=3.0)],raw)
    assert len(messages)==2 and 'quiet' in messages[0] and 'uncertain' in messages[1]
    assert raw=='taxis ' * 20


def test_full_recording_retry_accepted_without_changing_azure_configuration(monkeypatch):
    fake = fake_sdk(monkeypatch, result="Review these words")
    response = upload(vad=False)
    assert response.status_code == 200 and response.json()["text"] == "Review these words"
    assert fake.config.speech_recognition_language == "en-IN"
    assert isinstance(response.json()["warnings"], list)


@pytest.mark.parametrize("container,codec,extension", [("ogg", "libopus", "ogg"), ("mp3", "libmp3lame", "mp3"), ("mp4", "aac", "mp4"), ("flac", "flac", "flac")])
def test_additional_supported_formats_decode_without_asr(tmp_path, container, codec, extension):
    path = tmp_path / ("synthetic." + extension)
    with av.open(str(path), "w", format=container) as output:
        stream = output.add_stream(codec, rate=48000); stream.layout = "mono"
        samples = (np.sin(np.arange(48000) * 2 * np.pi * 440 / 48000) * 12000).astype(np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono"); frame.sample_rate = 48000
        for packet in stream.encode(frame): output.mux(packet)
        for packet in stream.encode(None): output.mux(packet)
    decoded, stats = inspect_audio(path)
    assert decoded.dtype == np.float32 and decoded.ndim == 1
    assert stats["decoded_sample_rate"] == 16000 and stats["decoded_channels"] == 1
    assert .95 <= stats["duration_seconds"] <= 1.1
    assert np.isfinite(decoded).all()
