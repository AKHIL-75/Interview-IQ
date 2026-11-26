"""Shared Azure transcription errors and non-destructive recognition warnings."""
import re
from collections import Counter


class STTServiceError(Exception):
    """Base exception for STT service errors."""
    pass


class ModelUnavailableError(STTServiceError):
    """Raised when Azure Speech is not configured or available."""
    pass


class TranscriptionError(STTServiceError):
    """Raised when transcription fails."""
    pass


class TranscriptionTimeoutError(STTServiceError):
    """Raised when transcription exceeds the timeout."""
    pass


class TranscriptionBusyError(STTServiceError):
    """The bounded upload transcription admission capacity is full."""


def recognition_warnings(audio_info, segments, text):
    """Heuristics flag review needs; they are not calibrated accuracy probabilities."""
    warnings = []
    if audio_info.get("rms_dbfs", 0) < -28:
        warnings.append("The recording is quiet. Speak at normal volume closer to the microphone and reduce fan/background noise before re-recording.")
    if audio_info.get("near_clip_fraction", 0) > .01:
        warnings.append("The recording may be distorted. Move slightly away from the microphone or reduce input gain.")
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    trigrams = list(zip(tokens, tokens[1:], tokens[2:]))
    repeated = bool(trigrams) and max(Counter(trigrams).values()) >= 5
    uncertain = any(getattr(segment, "avg_logprob", 0) < -1.0 or getattr(segment, "compression_ratio", 0) > 2.4 for segment in segments)
    if repeated or uncertain:
        warnings.append("Speech recognition was uncertain or repetitive in parts. Listen to the recording and check the transcript carefully; re-record if it does not match your words.")
    return warnings
