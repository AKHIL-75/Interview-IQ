"""Public problem responses never include exception text or submitted values."""
import logging
from http import HTTPStatus
from uuid import uuid4
import httpx

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

MESSAGES = {
    400: "The request could not be read. Please check your input.",
    401: "Missing authentication token or expired session. Please sign in again.",
    403: "You do not have permission to access this resource.",
    404: "The requested resource was not found or is not accessible.",
    405: "This request method is not supported.",
    409: "This action conflicts with saved interview progress. Resume the current question before retrying.",
    413: "The upload or request is too large. Resume limit: 10 MB; audio limit: 25 MB and 10 minutes.",
    415: "Unsupported file format. Resumes require PDF/DOCX; audio requires WebM, OGG, WAV, MP3, FLAC or MP4.",
    422: "Please check your input. If this is a recording, try recording again or type your answer.",
    429: "Too many requests. Please wait before retrying.",
    500: "The server could not complete this action. Please retry when the service is available.",
    502: "The processing service returned an invalid response. Please retry.",
    503: "A required service is temporarily unavailable. Please try again shortly.",
    504: "Processing timed out. Please retry the same action.",
}


def problem(status, *, request_id=None, headers=None):
    request_id = request_id or uuid4().hex
    title = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else "Request failed"
    return JSONResponse(
        {"type": "about:blank", "title": title, "status": status,
         "detail": MESSAGES.get(status, "The request could not be completed."),
         "request_id": request_id},
        status_code=status, media_type="application/problem+json",
        headers={**(headers or {}), "X-Request-Id": request_id},
    )


async def handle_http_error(request, exc):
    # Only server-owned protocol headers may escape the exception boundary.
    headers = {k: v for k, v in (exc.headers or {}).items()
               if k.lower() in {"www-authenticate", "retry-after", "allow"}}
    return problem(exc.status_code, headers=headers)


async def handle_validation_error(request, exc):
    # Pydantic errors may contain the complete answer, JWT or custom exception.
    return problem(422)


async def handle_unexpected_error(request, exc):
    request_id = uuid4().hex
    logging.getLogger("app.errors").error(
        "request_failed request_id=%s exception_type=%s", request_id, type(exc).__name__)
    return problem(500, request_id=request_id)


async def handle_dependency_error(request, exc):
    status = 504 if isinstance(exc, httpx.TimeoutException) else 503
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403}:
        status = exc.response.status_code
    logging.getLogger("app.errors").warning("dependency_failed exception_type=%s", type(exc).__name__)
    return problem(status)


def install_exception_handlers(app):
    app.add_exception_handler(HTTPException, handle_http_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(httpx.RequestError, handle_dependency_error)
    app.add_exception_handler(httpx.HTTPStatusError, handle_dependency_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
