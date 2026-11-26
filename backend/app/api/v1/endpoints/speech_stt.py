"""STT authorization uses its own resource; the TTS endpoint is untouched."""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from app.core.auth import AuthUser, get_current_auth
from app.core.config import settings
from app.services.azure_stt_service import AzureSTTError, resource_config
from app.services.stt_provider import start_stt, shutdown_stt

router = APIRouter(on_startup=[start_stt], on_shutdown=[shutdown_stt])


class STTTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str
    region: str
    expires_in_s: int


class STTConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    language: str
    endpoint: str | None = None


@router.get("/stt-config", response_model=STTConfigResponse, response_model_exclude_none=True)
async def stt_config(response: Response, auth: AuthUser = Depends(get_current_auth)):
    response.headers["Cache-Control"] = "no-store"
    enabled = True
    endpoint = None
    try:
        _, endpoint = resource_config()
    except (AzureSTTError, ValueError):
        enabled = False
    return STTConfigResponse(enabled=enabled, language=settings.AZURE_STT_LANGUAGE, endpoint=endpoint or None)


@router.post("/stt-token", response_model=STTTokenResponse)
async def stt_token(response: Response, auth: AuthUser = Depends(get_current_auth)):
    response.headers["Cache-Control"] = "no-store"
    try:
        region, endpoint = resource_config()
    except (AzureSTTError, ValueError):
        raise HTTPException(503, "Live captions are unavailable.") from None
    origin = endpoint or f"https://{region}.api.cognitive.microsoft.com"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            upstream = await client.post(origin + "/sts/v1.0/issueToken", content=b"", headers={
                "Ocp-Apim-Subscription-Key": settings.AZURE_STT_SPEECH_KEY.get_secret_value(),
                "Content-Type": "application/x-www-form-urlencoded", "Content-Length": "0",
            })
        if upstream.status_code != 200:
            raise HTTPException(503 if upstream.status_code in {429, 503, 504} else 502, "Live captions are unavailable.")
        token = upstream.text.strip()
        if not token or len(token) > 16384 or any(character.isspace() for character in token):
            raise HTTPException(502, "Live captions are unavailable.")
        return STTTokenResponse(token=token, region=region, expires_in_s=600)
    except httpx.RequestError:
        raise HTTPException(503, "Live captions are unavailable.") from None
