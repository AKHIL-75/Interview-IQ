"""
Health check endpoint for the Interview-IQ backend.

Provides a simple way to verify that the API server
is running and responding correctly.
"""

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from app.core.config import settings
from app.core.auth import get_current_auth
from app.core.inference import can_use_local_gpu


router = APIRouter()


@router.get("/inference/engines", response_model=dict[str, bool], dependencies=[Depends(get_current_auth)])
async def inference_engines(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    status = await request.app.state.engine_availability.read()
    return {**status, "local": status["local"] and can_use_local_gpu(request)}


class HealthResponse(BaseModel):
    """Response model for the health check endpoint."""

    status: str
    service: str
    version: str


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Returns the current health status of the Interview-IQ backend.",
)
def health_check() -> HealthResponse:
    """
    Health check endpoint.

    Returns a JSON object confirming the service is operational,
    along with the service name and current version.
    """
    return HealthResponse(
        status="ok",
        service="interview-iq-backend",
        version=settings.APP_VERSION,
    )
