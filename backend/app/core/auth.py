"""
Backend Authentication — Phase 11

Provides reusable FastAPI dependencies that:
  1. Read the Authorization: Bearer <token> header.
  2. Validate the Supabase JWT via GoTrue /auth/v1/user.
  3. Extract the authenticated user ID (UUID) and token.
  4. Reject invalid/expired tokens with 401 Unauthorized.

SECURITY:
  - User identity is derived strictly from the validated JWT — never from request body.
  - Uses public anon key and standard Supabase GoTrue token validation.
  - Preserves user context for RLS-protected database operations.
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
import time
from app.services.performance import metric

from app.core.config import settings


# HTTPBearer scheme — extracts "Bearer <token>" from Authorization header
_bearer_scheme = HTTPBearer(auto_error=False)


class AuthUser:
    """Represents a validated Supabase authenticated user."""

    def __init__(self, user_id: UUID, token: str, email: Optional[str] = None):
        self.user_id = user_id
        self.token = token
        self.email = email

    def __repr__(self) -> str:
        return "<AuthUser authenticated>"


async def get_current_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    request: Request = None,
) -> AuthUser:
    """
    Validates the Supabase JWT and returns the AuthUser with user_id and token.
    Raises HTTPException(401) if token is missing, invalid, or expired.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    # The upload preflight and endpoint share one validation on this request.
    cached = getattr(request.state, "_iiq_verified_auth", None) if request is not None else None
    if isinstance(cached, AuthUser) and cached.token == token:
        return cached

    if not settings.SUPABASE_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase is not configured on the backend.",
        )

    apikey = settings.SUPABASE_ANON_KEY
    if not apikey:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase API key is not configured on the backend.",
        )

    try:
        auth_start = time.perf_counter()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.SUPABASE_URL}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": apikey,
                },
            )

        metric("auth.validate", duration_ms=(time.perf_counter() - auth_start) * 1000)
        if response.status_code >= 500 or response.status_code == 429:
            raise HTTPException(503, "Authentication service is temporarily unavailable.")
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_data = response.json()
        user_id_str = user_data.get("id")

        if not user_id_str or user_data.get("is_anonymous") is True:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="A signed-in account is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        auth = AuthUser(
            user_id=UUID(user_id_str),
            token=token,
            email=user_data.get("email"),
        )
        if request is not None:
            request.state._iiq_verified_auth = auth
        return auth

    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Authentication service timed out.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(503, "Authentication service is temporarily unavailable.") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Authentication service returned an invalid response.",
        ) from exc


async def get_current_user_id(
    auth: AuthUser = Depends(get_current_auth),
) -> UUID:
    """
    FastAPI dependency that returns the authenticated user's UUID.
    Raises HTTPException(401) if not authenticated.
    """
    return auth.user_id


async def get_optional_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    request: Request = None,
) -> Optional[AuthUser]:
    """
    Optional auth dependency — returns AuthUser if valid Bearer token provided, None otherwise.
    Never raises 401 for missing credentials; only raises 401 if an invalid token was supplied.
    """
    if not credentials or not credentials.credentials:
        return None

    return await get_current_auth(credentials, request)


async def get_optional_user_id(
    auth: Optional[AuthUser] = Depends(get_optional_auth),
) -> Optional[UUID]:
    """
    Optional auth dependency — returns UUID if authenticated, None otherwise.
    """
    return auth.user_id if auth else None

