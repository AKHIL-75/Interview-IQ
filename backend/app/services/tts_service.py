"""Optional Azure speech synthesis. No text, audio, or SDK diagnostics are logged."""
import importlib
import threading

from app.core.config import settings
from app.schemas.speech import ALLOWED_AZURE_VOICES, DEFAULT_AZURE_VOICE


class SpeechUnavailableError(Exception):
    pass


class SpeechSynthesisError(Exception):
    pass


class SpeechTimeoutError(Exception):
    pass


class SpeechService:
    def __init__(self, timeout=20.0):
        self.timeout = timeout
        self._slots = threading.BoundedSemaphore(2)

    def synthesize(self, text, voice=DEFAULT_AZURE_VOICE):
        key = settings.AZURE_SPEECH_KEY.get_secret_value()
        region = settings.AZURE_SPEECH_REGION.strip()
        if not key or not region:
            raise SpeechUnavailableError() from None
        if voice not in ALLOWED_AZURE_VOICES or not text.strip() or len(text) > 3000:
            raise SpeechSynthesisError() from None
        if not self._slots.acquire(blocking=False):
            raise SpeechUnavailableError() from None
        synthesizer = None
        future = None
        done = threading.Event()

        def complete(event):
            done.set()

        try:
            try:
                sdk = importlib.import_module("azure.cognitiveservices.speech")
            except (ImportError, OSError):
                raise SpeechUnavailableError() from None
            config = sdk.SpeechConfig(subscription=key, region=region)
            config.speech_synthesis_voice_name = voice
            config.set_speech_synthesis_output_format(
                sdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
            )
            # None prevents playback on the server's speakers.
            synthesizer = sdk.SpeechSynthesizer(speech_config=config, audio_config=None)
            synthesizer.synthesis_completed.connect(complete)
            synthesizer.synthesis_canceled.connect(complete)
            future = synthesizer.speak_text_async(text)
            # SDK futures do not offer a timeout. Events let the worker wait only
            # for a bounded duration, including when the remote service stalls.
            if not done.wait(self.timeout):
                raise SpeechTimeoutError()
            # Resolve only after the terminal event; this also frees the SDK's
            # native async handle (ResultFuture has no automatic finalizer).
            result = future.get()
            if result.reason != sdk.ResultReason.SynthesizingAudioCompleted or not result.audio_data:
                raise SpeechSynthesisError()
            return bytes(result.audio_data)
        except (SpeechUnavailableError, SpeechTimeoutError, SpeechSynthesisError):
            raise
        except Exception:
            # Never propagate Azure cancellation details, keys, or endpoint diagnostics.
            raise SpeechSynthesisError() from None
        finally:
            if synthesizer is not None:
                try:
                    if not done.is_set():
                        synthesizer.stop_speaking_async().get()
                        if future is not None:
                            future.get()
                    synthesizer.synthesis_completed.disconnect_all()
                    synthesizer.synthesis_canceled.disconnect_all()
                except Exception:
                    pass
            self._slots.release()


speech_service = SpeechService()
