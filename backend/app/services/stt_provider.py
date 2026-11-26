"""Azure-only transcription with cancellation and shutdown ownership."""
import asyncio
import threading
import time
from contextlib import suppress

from app.core.config import settings
from app.services.azure_stt_service import AzureSTTError, AzureSTTService, STTStopped
from app.services.stt_service import ModelUnavailableError, TranscriptionError, TranscriptionTimeoutError, TranscriptionBusyError

_lock = threading.Lock()
_active = set()
_closing = threading.Event()
_azure = None


def start_stt():
    _closing.clear()


def shutdown_stt():
    with _lock:
        _closing.set()
        for event in _active:
            event.set()


async def transcribe_with_provider(path, vad_filter, request):
    global _azure
    started_at = time.monotonic()
    stop = threading.Event()
    with _lock:
        if _closing.is_set():
            raise STTStopped()
        # At most C running + C waiting jobs, before creating executor tasks.
        if len(_active) >= settings.AZURE_STT_MAX_CONCURRENCY * 2:
            raise TranscriptionBusyError("Audio transcription is busy.")
        _active.add(stop)
        if _azure is None:
            _azure = AzureSTTService(settings.AZURE_STT_MAX_CONCURRENCY)
    worker = None

    async def check():
        await asyncio.sleep(0)
        if stop.is_set() or _closing.is_set():
            stop.set()
            raise STTStopped()

    async def monitor():
        # The multipart body has already been consumed. Await the receive
        # channel: Request.is_disconnected() can miss disconnects behind the
        # application's BaseHTTPMiddleware because its probe cancels too early.
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                stop.set()
                raise STTStopped()

    async def run(function, *args, **kwargs):
        nonlocal worker
        await check()
        def invoke():
            if stop.is_set() or _closing.is_set():
                raise STTStopped()
            return function(*args, **kwargs)
        worker = asyncio.create_task(asyncio.to_thread(invoke))
        completed, _ = await asyncio.wait({worker, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if watcher in completed:
            await watcher
        await check()
        return await worker

    watcher = asyncio.create_task(monitor())
    try:
        try:
            result = await run(_azure.transcribe, path, stop, started_at=started_at)
        except AzureSTTError as error:
            await check()
            if error.category == "timeout":
                raise TranscriptionTimeoutError("Azure STT timed out.") from None
            if error.category == "unavailable":
                raise ModelUnavailableError("Azure STT is not configured or unavailable.") from None
            raise TranscriptionError("Azure STT could not transcribe this recording.") from None
        await check()
        return result
    finally:
        stop.set()
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        # Do not unlink the upload while the worker still decodes it. Azure checks
        # the stop flag cooperatively; no second transcription provider is started.
        if worker is not None:
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            with suppress(BaseException):
                worker.result()
        with _lock:
            _active.discard(stop)
