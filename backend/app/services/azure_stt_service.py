"""Optional Azure STT. No credentials, provider diagnostics or transcripts are logged."""
import asyncio
import importlib
import re
import threading
import time
from urllib.parse import urlsplit

import numpy as np

from app.core.config import settings
from app.services.audio_diagnostics import AudioDurationLimitError, inspect_audio
from app.services.stt_service import TranscriptionError, recognition_warnings


class AzureSTTError(Exception):
    """Only a fixed, non-sensitive category crosses the provider boundary."""
    def __init__(self, category="provider"):
        self.category = category
        super().__init__("Azure STT unavailable")


class STTStopped(asyncio.CancelledError):
    """Local cancellation is never a provider failure."""


def resource_config():
    region = settings.AZURE_STT_SPEECH_REGION.strip()
    endpoint = settings.AZURE_STT_ENDPOINT.strip().rstrip("/")
    if not re.fullmatch(r"[a-z][a-z0-9]+", region):
        raise AzureSTTError("unavailable")
    if endpoint:
        url = urlsplit(endpoint)
        if (url.scheme != "https" or url.username or url.password or url.port
                or url.path or url.query or url.fragment
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.cognitiveservices\.azure\.com", url.netloc)):
            raise AzureSTTError("unavailable")
    if not settings.AZURE_STT_SPEECH_KEY.get_secret_value().strip():
        raise AzureSTTError("unavailable")
    if not re.fullmatch(r"[a-z]{2,3}-[A-Za-z0-9-]+", settings.AZURE_STT_LANGUAGE):
        raise AzureSTTError("unavailable")
    return region, endpoint


def effective_timeout(duration):
    return min(settings.AZURE_STT_TIMEOUT_S, 630.0, duration * 1.0 + 30)


class AzureSTTService:
    def __init__(self, concurrency):
        self.slots = threading.BoundedSemaphore(concurrency)

    def transcribe(self, path, stop, *, started_at=None):
        start = time.monotonic() if started_at is None else started_at
        deadline = start + effective_timeout(600)
        acquired = False
        stream = recognizer = None
        start_future = None
        done = threading.Event()
        callbacks_lock = threading.Lock()
        state = {"text": [], "error": None, "stopped": False, "accepting": True}

        def check():
            if stop.is_set():
                raise STTStopped()
            if time.monotonic() >= deadline:
                raise AzureSTTError("timeout")

        try:
            check()
            while not acquired:
                acquired = self.slots.acquire(timeout=min(0.05, max(0, deadline - time.monotonic())))
                check()
            # Use exactly the existing decoder; its float32 output needs raw s16le for Azure.
            try:
                samples, audio = inspect_audio(path,
                    max_duration_seconds=min(600, settings.AZURE_STT_MAX_AUDIO_S), check=check)
            except (AzureSTTError, STTStopped):
                raise
            except AudioDurationLimitError:
                raise TranscriptionError("Audio exceeds the recording duration limit.") from None
            except Exception:
                raise TranscriptionError("Audio could not be decoded. Please re-record or type your answer.") from None
            check()
            duration = audio["duration_seconds"]
            if duration > 600:
                raise TranscriptionError("Audio exceeds the 10 minute recording limit.")
            if duration > settings.AZURE_STT_MAX_AUDIO_S:
                raise AzureSTTError("duration")
            deadline = start + effective_timeout(duration)
            check()
            region, endpoint = resource_config()
            try:
                sdk = importlib.import_module("azure.cognitiveservices.speech")
            except (ImportError, OSError):
                raise AzureSTTError("unavailable") from None
            key = settings.AZURE_STT_SPEECH_KEY.get_secret_value()
            if endpoint:
                config = sdk.SpeechConfig(subscription=key, endpoint=endpoint + "/stt/speech/recognition/conversation/cognitiveservices/v1")
            else:
                config = sdk.SpeechConfig(subscription=key, region=region)
            config.speech_recognition_language = settings.AZURE_STT_LANGUAGE
            stream = sdk.audio.PushAudioInputStream(sdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1))
            recognizer = sdk.SpeechRecognizer(speech_config=config, audio_config=sdk.audio.AudioConfig(stream=stream))
            phrases = [phrase.strip() for phrase in settings.AZURE_STT_PHRASE_LIST.split(",") if phrase.strip()]
            if phrases:
                grammar = sdk.PhraseListGrammar.from_recognizer(recognizer)
                for phrase in phrases:
                    grammar.addPhrase(phrase)

            def recognized(event):
                with callbacks_lock:
                    if state["accepting"] and not stop.is_set() and event.result.reason == sdk.ResultReason.RecognizedSpeech:
                        state["text"].append(event.result.text.strip())

            def canceled(event):
                with callbacks_lock:
                    if not state["accepting"]:
                        return
                    details = event.cancellation_details
                    if stop.is_set():
                        state["stopped"] = True
                    elif details.reason == sdk.CancellationReason.Error:
                        code = details.code
                        state["error"] = "timeout" if code == sdk.CancellationErrorCode.ServiceTimeout else "provider"
                    elif details.reason != sdk.CancellationReason.EndOfStream:
                        state["stopped"] = True
                    done.set()

            recognizer.recognized.connect(recognized)
            recognizer.canceled.connect(canceled)
            recognizer.session_stopped.connect(lambda event: done.set())
            # SDK async initiation does not block on ResultFuture.get(). Terminal events
            # and the deadline control the wait, including an unresponsive provider.
            start_future = recognizer.start_continuous_recognition_async()
            for offset in range(0, len(samples), 16000):
                check()
                if done.is_set():
                    break
                pcm = np.clip(samples[offset:offset + 16000] * 32768.0, -32768, 32767).astype("<i2").tobytes()
                stream.write(pcm)
            stream.close()
            while not done.wait(min(0.05, max(0, deadline - time.monotonic()))):
                check()
            check()
            with callbacks_lock:
                state["accepting"] = False
                if state["stopped"]:
                    raise STTStopped()
                if state["error"]:
                    raise AzureSTTError(state["error"])
                text = " ".join(part for part in state["text"] if part).strip()
            # Empty recognition is legitimate: signal energy alone cannot prove speech.
            return {"success": True, "text": text, "language": settings.AZURE_STT_LANGUAGE,
                    "language_probability": 0.0, "duration_seconds": duration,
                    "processing_time_ms": int((time.monotonic() - start) * 1000),
                    "model": "azure-stt:" + settings.AZURE_STT_LANGUAGE,
                    "audio": audio, "warnings": recognition_warnings(audio, [], text)}
        except (AzureSTTError, TranscriptionError, STTStopped):
            raise
        except Exception:
            if stop.is_set():
                raise STTStopped() from None
            raise AzureSTTError() from None
        finally:
            with callbacks_lock:
                state["accepting"] = False
                state["text"].clear()
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            if recognizer is not None:
                stop_future = None
                try:
                    stop_future = recognizer.stop_continuous_recognition_async()
                except Exception:
                    pass
                for signal in (recognizer.recognized, recognizer.canceled, recognizer.session_stopped):
                    try:
                        signal.disconnect_all()
                    except Exception:
                        pass
                # ResultFuture.get() releases native async handles, but has no
                # timeout. Keep the slot occupied until cleanup really finishes;
                # at most one daemon cleanup thread can exist per occupied slot.
                def reap(owner=recognizer, futures=(start_future, stop_future)):
                    try:
                        for future in futures:
                            if future is not None:
                                try:
                                    future.get()
                                except Exception:
                                    pass
                    finally:
                        self.slots.release()

                cleanup = threading.Thread(target=reap, name="azure-stt-cleanup", daemon=True)
                cleanup.start()
                acquired = False
                cleanup.join(timeout=min(0.05, max(0, deadline - time.monotonic())))
            if acquired:
                self.slots.release()
