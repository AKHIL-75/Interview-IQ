"""Authenticated MP3 question audio; text interviewing never depends on this route."""
from fastapi import APIRouter, Depends, HTTPException, Response
from starlette.concurrency import run_in_threadpool

from app.core.auth import AuthUser, get_current_auth
from app.schemas.speech import SpeechRequest
from app.services.tts_service import (
    speech_service, SpeechUnavailableError, SpeechSynthesisError, SpeechTimeoutError,
)

router = APIRouter()


@router.post("/synthesize", response_class=Response,
             responses={200: {"content": {"audio/mpeg": {}}}},
             summary="Speak an interviewer question using a supported Azure Neural voice")
async def synthesize_speech(payload: SpeechRequest, auth: AuthUser = Depends(get_current_auth)):
    try:
        audio = await run_in_threadpool(speech_service.synthesize, payload.text, payload.voice)
    except SpeechUnavailableError:
        raise HTTPException(503, "Question audio is unavailable.") from None
    except SpeechTimeoutError:
        raise HTTPException(504, "Question audio timed out.") from None
    except SpeechSynthesisError:
        raise HTTPException(502, "Question audio could not be generated.") from None
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
