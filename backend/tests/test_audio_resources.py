"""Bounded decode/admission tests; native interruption is deliberately not claimed."""
import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
import pytest
from app.services import audio_diagnostics as diagnostics
from app.services.stt_service import TranscriptionBusyError
from tests.test_azure_stt import isolated, fake_sdk, upload, request_stub, azure, provider, settings, assert_released


def decoder(monkeypatch, sizes):
    outputs, consumed = [], []
    for size in sizes:
        outputs.append(SimpleNamespace(samples=size, to_ndarray=Mock(return_value=np.zeros((1, size), dtype=np.int16))))
    def frames(**kwargs):
        for number, output in enumerate(outputs):
            consumed.append(number)
            yield SimpleNamespace(pts=number, output=output)
    container = SimpleNamespace(decode=frames, closed=False)
    class Container:
        def __enter__(self): return container
        def __exit__(self, *args): container.closed = True
    monkeypatch.setattr(diagnostics, "av", SimpleNamespace(open=lambda path: Container(),
        AudioResampler=lambda **kwargs: SimpleNamespace(resample=lambda frame: [] if frame is None else [frame.output])))
    return outputs, consumed, container


def test_decode_rejects_before_copy_or_concatenation_and_stops_reading(monkeypatch):
    outputs, consumed, container = decoder(monkeypatch, [160, 160, 160])
    concatenate = Mock(side_effect=AssertionError("Overlong samples were accumulated"))
    monkeypatch.setattr(diagnostics.np, "concatenate", concatenate)
    with pytest.raises(diagnostics.AudioDurationLimitError):
        diagnostics.decode_audio("synthetic", max_duration_seconds=.01)
    assert consumed == [0, 1] and container.closed
    outputs[0].to_ndarray.assert_called_once()
    outputs[1].to_ndarray.assert_not_called()
    outputs[2].to_ndarray.assert_not_called()
    concatenate.assert_not_called()


def test_decode_accepts_exact_sample_limit(monkeypatch):
    _, consumed, container = decoder(monkeypatch, [160, 160])
    result = diagnostics.decode_audio("synthetic", max_duration_seconds=.02)
    assert result.shape == (320,) and result.dtype == np.float32
    assert consumed == [0, 1] and container.closed


@pytest.mark.parametrize("failure", [azure.AzureSTTError("timeout"), azure.STTStopped()])
def test_decode_checks_deadline_or_cancellation_between_frames(monkeypatch, failure):
    outputs, consumed, container = decoder(monkeypatch, [160, 160, 160])
    checks = 0
    def check():
        nonlocal checks
        checks += 1
        if checks == 4: raise failure
    with pytest.raises(type(failure)):
        diagnostics.decode_audio("synthetic", max_duration_seconds=600, check=check)
    assert container.closed and consumed == [0, 1]
    outputs[1].to_ndarray.assert_not_called()


def track_tempfiles(monkeypatch):
    from app.api.v1.endpoints import audio
    created = []
    original = audio.tempfile.mkstemp
    def create(**kwargs):
        result = original(**kwargs); created.append(Path(result[1])); return result
    monkeypatch.setattr(audio.tempfile, "mkstemp", create)
    return created


def test_real_overlong_decode_rejected_before_azure_and_tempfile_removed(monkeypatch):
    fake = fake_sdk(monkeypatch)
    monkeypatch.setattr(settings, "AZURE_STT_MAX_AUDIO_S", 1)
    monkeypatch.setattr(azure, "inspect_audio", diagnostics.inspect_audio)
    created = track_tempfiles(monkeypatch)
    source = Path(__file__).parent / "fixtures" / "synthetic_candidate.wav"
    response = upload(content=source.read_bytes(), mime="audio/wav")
    assert response.status_code == 422
    fake.sdk.SpeechRecognizer.assert_not_called()
    assert created and all(not path.exists() for path in created)
    assert provider._azure.slots.acquire(blocking=False)
    provider._azure.slots.release()


def test_decode_timeout_maps_to_504_without_azure_and_cleans_file(monkeypatch):
    fake = fake_sdk(monkeypatch)
    def inspect(path, *, max_duration_seconds, check):
        assert max_duration_seconds == 600
        raise azure.AzureSTTError("timeout")
    monkeypatch.setattr(azure, "inspect_audio", inspect)
    created = track_tempfiles(monkeypatch)
    response = upload()
    assert response.status_code == 504
    fake.sdk.SpeechRecognizer.assert_not_called()
    assert created and all(not path.exists() for path in created)
    assert provider._azure.slots.acquire(blocking=False)
    provider._azure.slots.release()


def test_elapsed_decode_deadline_before_sdk_start_releases_slot(monkeypatch):
    fake = fake_sdk(monkeypatch)
    monkeypatch.setattr(settings, "AZURE_STT_TIMEOUT_S", .02)
    inspect = azure.inspect_audio
    def delayed_decode(*args, **kwargs):
        time.sleep(.04)
        return inspect(*args, **kwargs)
    monkeypatch.setattr(azure, "inspect_audio", delayed_decode)
    created = track_tempfiles(monkeypatch)
    assert upload().status_code == 504
    fake.sdk.SpeechRecognizer.assert_not_called()
    assert created and all(not path.exists() for path in created)
    assert provider._azure.slots.acquire(blocking=False)
    provider._azure.slots.release()


def test_deadline_includes_admission_wait_and_has_630_second_ceiling(monkeypatch):
    fake = fake_sdk(monkeypatch)
    monkeypatch.setattr(settings, "AZURE_STT_TIMEOUT_S", 900)
    monkeypatch.setattr(azure, "time", SimpleNamespace(monotonic=lambda: 631.0))
    service = azure.AzureSTTService(1)
    with pytest.raises(azure.AzureSTTError) as error:
        service.transcribe("synthetic", threading.Event(), started_at=0)
    assert error.value.category == "timeout"
    azure.inspect_audio.assert_not_called()
    fake.sdk.SpeechRecognizer.assert_not_called()
    assert service.slots.acquire(blocking=False)
    service.slots.release()


def test_decoded_duration_shortens_total_budget_including_queue_time(monkeypatch):
    fake = fake_sdk(monkeypatch, duration=2)
    monkeypatch.setattr(azure, "time", SimpleNamespace(monotonic=lambda: 34.0))
    service = azure.AzureSTTService(1)
    with pytest.raises(azure.AzureSTTError) as error:
        service.transcribe("synthetic", threading.Event(), started_at=0)
    assert error.value.category == "timeout"
    azure.inspect_audio.assert_called_once()
    fake.sdk.SpeechRecognizer.assert_not_called()
    assert service.slots.acquire(blocking=False)
    service.slots.release()


def test_two_admitted_jobs_bound_queue_and_third_upload_gets_429(monkeypatch):
    fake = fake_sdk(monkeypatch, stalled=True)
    created = track_tempfiles(monkeypatch)
    async def exercise():
        first = asyncio.create_task(provider.transcribe_with_provider("first", None, request_stub()))
        second = None
        try:
            deadline = time.monotonic() + 2
            while not fake.started.is_set():
                assert time.monotonic() < deadline
                await asyncio.sleep(.001)
            second = asyncio.create_task(provider.transcribe_with_provider("second", None, request_stub()))
            while len(provider._active) != 2:
                assert time.monotonic() < deadline
                await asyncio.sleep(.001)
            response = await asyncio.to_thread(upload)
            assert response.status_code == 429
            assert response.headers["retry-after"] == "1"
            assert response.headers["content-type"] == "application/problem+json"
            assert len(provider._active) == 2
            assert created and all(not path.exists() for path in created)
            fake.sdk.SpeechRecognizer.assert_called_once()
            azure.inspect_audio.assert_called_once()
        finally:
            for task in [second, first]:
                if task is not None:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(exercise())
    assert not provider._active
    assert_released(fake)


@pytest.mark.parametrize("action", ["cancel", "disconnect", "shutdown"])
def test_native_decode_cancellation_retains_admission_until_worker_releases(monkeypatch, action):
    import io
    from starlette.datastructures import UploadFile, Headers
    from app.api.v1.endpoints import audio
    fake = fake_sdk(monkeypatch)
    created = track_tempfiles(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def inspect(path, *, max_duration_seconds, check):
        entered.set()
        release.wait(2)  # Simulates a native call that cannot be interrupted.
        check()
        raise AssertionError("Cancellation must be observed after native return")
    monkeypatch.setattr(azure, "inspect_audio", inspect)
    async def exercise():
        request = request_stub()
        file = UploadFile(io.BytesIO(b"fixture"), filename="native.wav", headers=Headers({"content-type": "audio/wav"}))
        task = asyncio.create_task(audio.transcribe_audio(request, file, None))
        try:
            deadline = time.monotonic() + 1
            while not entered.is_set():
                assert time.monotonic() < deadline
                await asyncio.sleep(.001)
            if action == "cancel": task.cancel()
            elif action == "disconnect": request.is_disconnected.return_value = True
            else: provider.shutdown_stt()
            await asyncio.sleep(.02)
            assert not task.done()
            assert len(provider._active) == 1
            assert not provider._azure.slots.acquire(blocking=False)
            assert created and all(path.exists() for path in created)
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(exercise())
    assert not provider._active
    assert all(not path.exists() for path in created)
    fake.sdk.SpeechRecognizer.assert_not_called()
    assert provider._azure.slots.acquire(timeout=1)
    provider._azure.slots.release()
