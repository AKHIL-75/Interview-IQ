"""Offline settings and free-router contracts using synthetic credentials only."""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings, settings
from app.services import llm_service, llm_usage

SECRET = "synthetic-settings-private-sentinel"
SECRET_FIELDS = ("OPENROUTER_API_KEY", "AZURE_SPEECH_KEY", "AZURE_STT_SPEECH_KEY")
REAL_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)


def free_settings(**overrides):
    return Settings(_env_file=None, **{
        "LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": SECRET,
        "OPENROUTER_PRIMARY_MODEL": "openrouter/free",
        "OPENROUTER_FALLBACK_MODELS": "", "OPENROUTER_FREE_ONLY": True,
        **overrides,
    })


def test_source_defaults_contain_no_provider_credentials():
    cfg = Settings(_env_file=None)
    for name in SECRET_FIELDS:
        assert isinstance(getattr(cfg, name), SecretStr)
        assert not getattr(cfg, name).get_secret_value()
    assert cfg.LLM_PROVIDER == "ollama"
    assert cfg.OLLAMA_MODEL == "qwen3:4b"
    assert not cfg.SUPABASE_SERVICE_ROLE_KEY


def test_dotenv_process_and_explicit_value_precedence(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=openrouter\nOPENROUTER_API_KEY=" + SECRET +
                   "\nOPENROUTER_PRIMARY_MODEL=openrouter/free\n"
                   "OPENROUTER_FALLBACK_MODELS=\nOPENROUTER_FREE_ONLY=true\n"
                   "AZURE_SPEECH_KEY=synthetic-tts\nAZURE_SPEECH_REGION=eastasia\n"
                   "AZURE_STT_SPEECH_KEY=synthetic-stt\nAZURE_STT_SPEECH_REGION=eastasia\n"
                   "SUPABASE_ANON_KEY=synthetic-public-anon\n", encoding="utf-8")
    cfg = Settings(_env_file=env)
    assert cfg.OPENROUTER_API_KEY.get_secret_value() == SECRET
    assert cfg.openrouter_models == ["openrouter/free"]
    assert cfg.AZURE_SPEECH_KEY.get_secret_value() == "synthetic-tts"
    assert cfg.AZURE_STT_SPEECH_KEY.get_secret_value() == "synthetic-stt"
    assert cfg.SUPABASE_ANON_KEY == "synthetic-public-anon"
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-process-key")
    assert Settings(_env_file=env).OPENROUTER_API_KEY.get_secret_value() == "synthetic-process-key"
    assert Settings(_env_file=env, OPENROUTER_API_KEY="synthetic-explicit").OPENROUTER_API_KEY.get_secret_value() == "synthetic-explicit"


def test_backend_dotenv_path_is_absolute_and_independent_of_cwd(tmp_path, monkeypatch):
    expected = Path(__file__).resolve().parents[1] / ".env"
    monkeypatch.chdir(tmp_path)
    assert Path(Settings.model_config["env_file"]) == expected


def test_secrets_redacted_in_repr_json_and_configuration_errors():
    cfg = free_settings(AZURE_SPEECH_KEY=SECRET, AZURE_STT_SPEECH_KEY=SECRET)
    assert SECRET not in repr(cfg) + str(cfg) + cfg.model_dump_json()
    with pytest.raises(ValidationError) as err:
        free_settings(OPENROUTER_TIMEOUT_S=0)
    assert SECRET not in str(err.value)


@pytest.mark.parametrize("key", ["", " ", "\t\n"])
def test_cloud_requires_nonblank_key_but_ollama_remains_optional(key):
    with pytest.raises(ValidationError, match="backend API key"):
        free_settings(OPENROUTER_API_KEY=key)
    assert free_settings(LLM_PROVIDER="ollama", OPENROUTER_API_KEY=key).LLM_PROVIDER == "ollama"


@pytest.mark.parametrize("fallbacks", ["", " ", ",,", " , \t, "])
def test_empty_fallbacks_cannot_restore_paid_defaults(fallbacks):
    assert free_settings(OPENROUTER_FALLBACK_MODELS=fallbacks).openrouter_models == ["openrouter/free"]


@pytest.mark.parametrize("changes", [
    {"OPENROUTER_PRIMARY_MODEL": "openrouter/auto"},
    {"OPENROUTER_PRIMARY_MODEL": "openai/gpt-4.1-mini"},
    {"OPENROUTER_FALLBACK_MODELS": "openai/gpt-4.1-mini"},
    {"OPENROUTER_FALLBACK_MODELS": "test/model:free,google/gemini-2.5-flash"},
])
def test_free_only_rejects_paid_or_auto_models(changes):
    with pytest.raises(ValidationError, match="exclusively free"):
        free_settings(**changes)


def test_explicit_free_fallbacks_are_trimmed_and_remain_bounded():
    cfg = free_settings(OPENROUTER_FALLBACK_MODELS=" test/first:free, test/second:free ")
    assert cfg.openrouter_models == ["openrouter/free", "test/first:free", "test/second:free"]
    for value in ("openrouter/free", "test/a:free,test/a:free", "test/a:free,test/b:free,test/c:free"):
        with pytest.raises(ValidationError, match="distinct fallback"):
            free_settings(OPENROUTER_FALLBACK_MODELS=value)


@pytest.mark.parametrize("url", [
    "http://openrouter.ai/api/v1", "https://evil.invalid/api/v1",
    "https://openrouter.ai.evil.invalid/api/v1", "https://user:pass@openrouter.ai/api/v1",
    "https://openrouter.ai:443/api/v1", "https://openrouter.ai/api/v1?key=private",
    "https://openrouter.ai/api/v1#fragment", "https://openrouter.ai/other",
])
def test_official_origin_validation_is_preserved(url):
    with pytest.raises(ValidationError, match="official HTTPS"):
        free_settings(OPENROUTER_BASE_URL=url)


def test_free_router_transport_sends_one_model_and_keeps_privacy_and_json_validation(monkeypatch, caplog):
    cfg = free_settings()
    for name in Settings.model_fields:
        monkeypatch.setattr(settings, name, getattr(cfg, name))
    calls = []
    prompt = 'Reply with JSON only: {"answer":"OPENROUTER_TEST_OK"}'
    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer " + SECRET
        payload = json.loads(request.content)
        assert payload["models"] == ["openrouter/free"]
        assert payload["provider"] == {"require_parameters": True, "data_collection": "deny",
                                       "zdr": True, "allow_fallbacks": True}
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"model": "test/serving-model:free", "provider": "SyntheticProvider",
            "choices": [{"message": {"content": '{"answer":"OPENROUTER_TEST_OK"}'}, "finish_reason": "stop"}]})
    async def invoke():
        with patch.object(llm_service.httpx, "AsyncClient", side_effect=lambda **kw:
                REAL_CLIENT(transport=httpx.MockTransport(handler), **kw)), llm_usage.capture_usage() as events:
            result = await llm_service.generate_json_response(prompt, timeout=1, num_predict=64)
        assert result == {"answer": "OPENROUTER_TEST_OK"}
        assert len(calls) == 1 and events[0]["http_status"] == 200
        assert events[0]["actual_model"] == "test/serving-model:free"
    caplog.set_level("INFO")
    asyncio.run(invoke())
    assert SECRET not in caplog.text and prompt not in caplog.text
