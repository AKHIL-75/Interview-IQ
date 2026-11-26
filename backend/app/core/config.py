"""
Application configuration using pydantic-settings.

Loads settings from environment variables and .env file.
Can be extended in later phases without restructuring.
"""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration for the Interview-IQ backend.

    Values are loaded from environment variables first,
    then from the .env file in the backend directory.
    """

    # Application metadata
    APP_NAME: str = "Interview-IQ Backend"
    APP_VERSION: str = "1.0.0"
    PERFORMANCE_DIAGNOSTICS: bool = False  # Local development only; no payload logging.

    # Frontend URL for CORS configuration
    FRONTEND_URL: str = "http://localhost:5173"
    # Preserve existing Vite development aliases; Compose explicitly clears these.
    CORS_EXTRA_ORIGINS: str = "http://127.0.0.1:5173,http://localhost:5174"

    @field_validator("FRONTEND_URL", "CORS_EXTRA_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, value, info):
        origins = [part.strip() for part in value.split(",") if part.strip()]
        if info.field_name == "FRONTEND_URL" and len(origins) != 1:
            raise ValueError("FRONTEND_URL must contain exactly one HTTP(S) origin")
        for origin in origins:
            parsed = urlsplit(origin)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username or parsed.password or parsed.path
                    or parsed.query or parsed.fragment or "*" in origin):
                raise ValueError("CORS origins must be exact HTTP(S) origins without paths")
        return ",".join(origins)

    @property
    def cors_origins(self) -> list[str]:
        return list(dict.fromkeys([self.FRONTEND_URL] + [
            origin for origin in self.CORS_EXTRA_ORIGINS.split(",") if origin]))

    # API versioning prefix
    API_V1_PREFIX: str = "/api/v1"

    # --- Phase 3: Ollama / LLM Configuration ---
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    AWS_OLLAMA_BASE_URL: str = ""
    DEFAULT_INFERENCE_ENGINE: Literal["local", "aws"] = "local"
    AWS_OLLAMA_RESUME_NUM_CTX: int = Field(default=2048, gt=0)
    AWS_OLLAMA_NUM_THREADS: int | None = Field(default=None, gt=0)
    INFERENCE_SERIAL_ADMISSION: bool = False
    STAGING_GPU_REVIEWER_ONLY: bool = False
    OLLAMA_MODEL: str = "qwen3:4b"
    OLLAMA_KEEP_ALIVE: str = "10m"
    OLLAMA_PREWARM_ENABLED: bool = False
    OLLAMA_TIMEOUT: float = 120.0
    OLLAMA_NUM_PREDICT: int = 300
    OLLAMA_THINK: bool = False

    # Explicit backend opt-in; no cloud calls in the default configuration.
    LLM_PROVIDER: Literal["ollama", "openrouter"] = "ollama"
    LLM_OPERATION_TIMEOUT_S: float = Field(default=150, gt=0, le=600, allow_inf_nan=False)
    OPENROUTER_API_KEY: SecretStr = SecretStr("")
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_PRIMARY_MODEL: str = "qwen/qwen3-235b-a22b-2507"
    OPENROUTER_FALLBACK_MODELS: str = "openai/gpt-4.1-mini,google/gemini-2.5-flash"
    OPENROUTER_TIMEOUT_S: float = Field(default=45, gt=0, le=150, allow_inf_nan=False)
    OPENROUTER_BENCHMARK_ENABLED: bool = False
    OPENROUTER_ZDR: bool = True
    OPENROUTER_FREE_ONLY: bool = False

    @field_validator("OPENROUTER_BASE_URL")
    @classmethod
    def validate_openrouter_url(cls, value):
        # Never send a bearer key to a configurable third-party host or redirect.
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc != "openrouter.ai"
                or parsed.path.rstrip("/") != "/api/v1" or parsed.query or parsed.fragment):
            raise ValueError("OPENROUTER_BASE_URL must be the official HTTPS API origin and /api/v1 path")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_llm(self):
        import re
        models = self.openrouter_models
        if not 1 <= len(models) <= 3 or len(models) != len(set(models)):
            raise ValueError("Configure one primary and at most two distinct fallback models")
        if any(not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.:-]+", m) for m in models):
            raise ValueError("Invalid OpenRouter model ID format")
        if self.OPENROUTER_FREE_ONLY and any(not (m.endswith(":free") or m == "openrouter/free") for m in models):
            raise ValueError("Free-only routing requires exclusively free model IDs")
        if self.LLM_PROVIDER == "openrouter" and not self.OPENROUTER_API_KEY.get_secret_value().strip():
            raise ValueError("OpenRouter requires a backend API key")
        return self

    @property
    def openrouter_models(self) -> list[str]:
        return [self.OPENROUTER_PRIMARY_MODEL.strip()] + [
            model.strip() for model in self.OPENROUTER_FALLBACK_MODELS.split(",") if model.strip()]

    # --- Phase 11: Supabase Configuration ---
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Azure Neural TTS is optional; credentials stay on the backend.
    AZURE_SPEECH_KEY: SecretStr = SecretStr("")
    AZURE_SPEECH_REGION: str = ""

    # Azure Speech is the sole STT resource; TTS credentials remain independent.
    AZURE_STT_SPEECH_KEY: SecretStr = SecretStr("")
    AZURE_STT_SPEECH_REGION: str = ""
    AZURE_STT_ENDPOINT: str = ""
    AZURE_STT_LANGUAGE: str = "en-IN"
    AZURE_STT_TIMEOUT_S: float = Field(default=630, gt=0, allow_inf_nan=False)
    AZURE_STT_MAX_AUDIO_S: float = Field(default=600, gt=0, allow_inf_nan=False)
    AZURE_STT_MAX_CONCURRENCY: int = Field(default=1, ge=1)
    AZURE_STT_PHRASE_LIST: str = ""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        hide_input_in_errors=True,
    )


# Singleton settings instance used throughout the application
settings = Settings()
