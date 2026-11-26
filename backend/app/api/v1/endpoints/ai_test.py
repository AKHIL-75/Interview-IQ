"""
AI Test Endpoint — Phase 3 verification.

POST /api/v1/ai/test

Proves that the backend can:
  1. Receive a request.
  2. Send a prompt to Qwen3 through Ollama.
  3. Parse the model's JSON output.
  4. Validate the structure with Pydantic.
  5. Return a clean, structured response.
"""
from app.services.llm_service import OpenRouterError, LLMTimeoutError


import json
import time
from typing import Callable

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services import llm_usage
from app.prompts.ai_test import AI_TEST_PROMPT, build_ai_test_prompt
from app.services.llm_service import (
    generate_json_response,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
    LLMResponseParseError,
    LLMServiceError,
)


class MultilineJsonRoute(APIRoute):
    """
    APIRoute that permits unescaped newlines and control characters inside
    string values when decoding JSON request bodies (e.g. multiline prompt
    inputs typed or pasted into Swagger UI). Truly malformed JSON is still
    rejected with HTTP 422.
    """

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                body = await request.body()
                if body:
                    try:
                        # strict=False permits literal newlines/control characters inside strings
                        request._json = json.loads(body, strict=False)
                    except json.JSONDecodeError:
                        # Fall through to original handler so FastAPI produces standard 422 RequestValidationError
                        pass
            return await original_route_handler(request)

        return custom_route_handler


router = APIRouter(route_class=MultilineJsonRoute)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class AITestRequest(BaseModel):
    """Request body for the AI test endpoint."""
    prompt: str = Field(
        default="",
        max_length=2000,
        description=(
            "Optional custom prompt override. Leave empty to use the default test prompt. "
            "Bounded to 2,000 characters for test safety; document-scale inputs in future "
            "phases (resumes, JDs) use dedicated schemas."
        ),
    )


class AITestResponse(BaseModel):
    """Validated response from the AI test endpoint."""
    message: str = Field(..., description="Confirmation message from the model.")
    model: str = Field(..., description="Model name that generated the response.")
    success: bool = Field(..., description="Whether the model reported success.")
    latency_ms: int = Field(..., description="Round-trip inference time in milliseconds.")
    ollama_model: str = Field(..., description="Ollama model tag used for inference.")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/ai/test",
    response_model=AITestResponse,
    summary="Test AI / LLM Connection",
    description=(
        "Sends a test prompt to the locally running Qwen3 model via Ollama "
        "and returns the validated JSON response.  Use this to verify that "
        "the AI inference pipeline is working."
    ),
)
@llm_usage.operation("diagnostic")
async def ai_test(body: AITestRequest) -> AITestResponse:
    """
    Test the Ollama / Qwen3 integration.

    1. Uses the default test prompt (or an optional override).
    2. Calls llm_service.generate_json_response().
    3. Validates the returned JSON against the expected schema.
    4. Returns the validated response with latency measurement.
    """
    prompt = build_ai_test_prompt(body.prompt)

    start = time.perf_counter()

    try:
        with llm_usage.capture_usage() as attempts:
            result = await generate_json_response(prompt)
    except OpenRouterError as err:
        raise HTTPException(err.status_code, "The inference provider could not complete the request.") from None
    except OllamaConnectionError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Ollama is not running. "
                "Start Ollama and try again (run 'ollama serve' in a terminal)."
            ),
        )
    except OllamaModelNotFoundError:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Model '{settings.OLLAMA_MODEL}' is not available in Ollama. "
                f"Pull it first with: ollama pull {settings.OLLAMA_MODEL}"
            ),
        )
    except LLMTimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Ollama timed out while generating the response. Try again later.",
        )
    except LLMResponseParseError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Model returned invalid JSON: {exc}",
        )
    except LLMServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM service error: {exc}",
        )

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    # --- Extract and validate expected fields ---
    message = result.get("message")
    model_name = result.get("model")
    success = result.get("success")

    # Resilient field extraction if the model used alternative key names
    if not message:
        if "output" in result:
            out = result["output"]
            if isinstance(out, dict):
                # E.g. {"2+2": "4", "which_model_am_i": "Qwen", ...}
                message = "; ".join(f"{k}: {v}" for k, v in out.items())
            else:
                message = str(out)
        elif "answer" in result:
            message = str(result["answer"])
        elif "response" in result:
            message = str(result["response"])

    if not model_name:
        model_name = (
            result.get("which_model_am_i")
            or result.get("model_name")
            or settings.OLLAMA_MODEL
        )

    if success is None:
        success = True

    if not message or not model_name:
        raise HTTPException(
            status_code=502,
            detail=(
                "Model response is missing required fields. "
                f"Expected 'message', 'model', 'success'. Got: {list(result.keys())}"
            ),
        )

    return AITestResponse(
        message=str(message),
        model=(attempts[-1].get("actual_model") or "unavailable") if attempts else "unavailable",
        success=bool(success),
        latency_ms=elapsed_ms,
        ollama_model=settings.OLLAMA_MODEL if settings.LLM_PROVIDER == "ollama" else "",
    )

