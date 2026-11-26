"""
Audio Transcription API — Phase 15

Provides POST /api/v1/audio/transcribe endpoint for browser-captured audio.
Accepts multipart/form-data with audio files, validates, and transcribes
using Azure Speech.

No audio is persisted permanently — temporary files are cleaned up after transcription.
Azure is the sole transcription provider.
"""

import os
import time
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Request
from fastapi.dependencies.utils import get_dependant
from fastapi.routing import APIRoute, get_request_handler
from app.core.auth import AuthUser, get_current_auth
from app.core.config import settings
from pydantic import BaseModel
from typing import Optional

from app.services.stt_service import (
    ModelUnavailableError,
    TranscriptionError,
    TranscriptionTimeoutError,
    TranscriptionBusyError,
)

logger = logging.getLogger("app.api.audio")

async def _authorize_upload(auth: AuthUser = Depends(get_current_auth)):
    """Dependency-only preflight: never parse a body or serialize credentials."""
    return None


class AuthenticatedAudioRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        # FastAPI normally parses forms before dependencies. This body-free
        # route resolves the same auth dependency first, including overrides.
        authorization = get_dependant(path=self.path_format, call=_authorize_upload)

        async def authenticated(request: Request):
            # Included routes resolve overrides from the serving application.
            authorize = get_request_handler(
                dependant=authorization, dependency_overrides_provider=request.app,
            )
            await authorize(request)
            return await handler(request)

        return authenticated


router = APIRouter(route_class=AuthenticatedAudioRoute)

# --- Configuration ---
MAX_AUDIO_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB max
MAX_AUDIO_DURATION_SECONDS = 600          # 10 minutes max (validated post-transcription)

# Allowed audio MIME types and their file extensions
ALLOWED_MIME_TYPES = {
    "audio/webm": ".webm",
    "audio/webm;codecs=opus": ".webm",
    "audio/ogg": ".ogg",
    "audio/ogg;codecs=opus": ".ogg",
    "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "application/octet-stream": ".webm",  # Fallback for browsers that don't set MIME
}


class TranscriptionResponse(BaseModel):
    """Response schema for audio transcription."""
    success: bool
    text: str
    language: str
    language_probability: float
    duration_seconds: float
    processing_time_ms: int
    model: str
    total_time_ms: int = 0
    audio: dict | None = None
    warnings: list[str] = []


@router.post(
    "/transcribe",
    response_model=TranscriptionResponse,
    summary="Transcribe audio using Azure Speech",
    description=(
        "Accepts an audio file (WebM, OGG, WAV, MP3, FLAC, MP4) and returns "
        "a text transcription using Azure Speech. No audio is stored permanently."
    ),
)
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(..., description="Audio file to transcribe"),
    vad_filter: Optional[bool] = Form(None, description="Optional full-audio retry when quiet words were filtered"),
    auth: AuthUser = Depends(get_current_auth),
):
    """
    Transcribe uploaded audio using Azure Speech.
    
    The audio file is:
    1. Validated for size and MIME type
    2. Written to a temporary file
    3. Transcribed using the Azure Speech model
    4. Temporary file is deleted immediately after transcription
    
    No audio data is persisted permanently.
    """
    request_start = time.time()
    
    # --- Validate content type ---
    content_type = (file.content_type or "").lower().strip()
    # Normalize: strip parameters after semicolon for matching, but also try exact match
    base_mime = content_type.split(";")[0].strip()
    
    if content_type not in ALLOWED_MIME_TYPES and base_mime not in ALLOWED_MIME_TYPES:
        logger.warning('transcribe_audio: [Audio] Rejected unsupported MIME type')
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio format: {content_type}. "
                   f"Supported formats: WebM, OGG, WAV, MP3, FLAC, MP4."
        )
    
    # Determine file extension for temp file
    file_ext = ALLOWED_MIME_TYPES.get(content_type) or ALLOWED_MIME_TYPES.get(base_mime, ".webm")
    
    # --- Read and validate file content ---
    try:
        audio_bytes = await file.read(MAX_AUDIO_SIZE_BYTES + 1)
    except Exception as e:
        logger.error('transcribe_audio: [Audio] Failed to read uploaded file')
        raise HTTPException(status_code=400, detail="Failed to read uploaded audio file.")
    
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty (0 bytes).")
    
    if len(audio_bytes) > MAX_AUDIO_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio file too large ({len(audio_bytes)} bytes). "
                   f"Maximum allowed: {MAX_AUDIO_SIZE_BYTES // (1024 * 1024)} MB."
        )
    
    logger.info('transcribe_audio: transcribe_audio')
    
    # --- Write to temporary file ---
    temp_path = None
    try:
        # Create temp file with correct extension for audio decoder compatibility
        fd, temp_path = tempfile.mkstemp(suffix=file_ext, prefix="iiq_audio_")
        with os.fdopen(fd, "wb") as audio_file:
            audio_file.write(audio_bytes)
        
        logger.info('transcribe_audio: transcribe_audio')
        
        # --- Transcribe ---
        from app.services.stt_provider import transcribe_with_provider
        result = await transcribe_with_provider(temp_path, vad_filter, request)
        
        if not result.get("success"):
            raise TranscriptionError("Transcription returned unsuccessful result")
        
        # Validate transcription output
        text = result.get("text", "").strip()
        
        # Check audio duration
        duration = result.get("duration_seconds", 0)
        if duration > MAX_AUDIO_DURATION_SECONDS:
            raise HTTPException(
                status_code=413,
                detail=f"Audio duration ({duration:.0f}s) exceeds maximum ({MAX_AUDIO_DURATION_SECONDS}s)."
            )
        
        total_time_ms = int((time.time() - request_start) * 1000)
        
        logger.info('transcribe_audio: [Audio] Transcription complete')
        
        return TranscriptionResponse(
            success=True,
            text=text,
            language=result.get("language", "unknown"),
            language_probability=result.get("language_probability", 0.0),
            duration_seconds=duration,
            processing_time_ms=result.get("processing_time_ms", total_time_ms),
            model=result.get("model", "unknown"),
            total_time_ms=total_time_ms,
            audio=result.get("audio"),
            warnings=result.get("warnings", []),
        )
    
    except HTTPException:
        raise
    except TranscriptionBusyError:
        raise HTTPException(429, "Audio transcription is busy. Please retry shortly.",
                            headers={"Retry-After": "1"}) from None
    except ModelUnavailableError as e:
        logger.error('transcribe_audio: [Audio] Azure Speech unavailable')
        raise HTTPException(
            status_code=503,
            detail=f"Speech-to-text model is unavailable: {str(e)}"
        )
    except TranscriptionTimeoutError as e:
        logger.error('transcribe_audio: [Audio] Transcription timeout')
        raise HTTPException(
            status_code=504,
            detail=f"Transcription timed out: {str(e)}"
        )
    except TranscriptionError as e:
        logger.error('transcribe_audio: [Audio] Transcription error')
        raise HTTPException(
            status_code=422,
            detail=f"Failed to transcribe audio: {str(e)}"
        )
    except Exception as e:
        logger.error('transcribe_audio: [Audio] Unexpected error during transcription')
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred during transcription."
        )
    finally:
        # --- ALWAYS clean up temporary audio file ---
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
                logger.info('transcribe_audio: transcribe_audio')
            except Exception as cleanup_err:
                logger.warning('transcribe_audio: [Audio] Failed to clean up temp file')
