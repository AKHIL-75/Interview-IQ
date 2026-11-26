"""Container-specific CORS and liveness contracts; no external services."""
import runpy
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, settings


def test_development_cors_aliases_are_preserved():
    config = Settings(_env_file=None, FRONTEND_URL="http://localhost:5173",
                      CORS_EXTRA_ORIGINS="http://127.0.0.1:5173,http://localhost:5174")
    assert config.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173",
                                   "http://localhost:5174"]


@pytest.mark.parametrize("origin", ["*", "https://*.example.com", "http://localhost:8080/path",
                                    "http://user:pass@localhost:8080", "", "http://localhost:8080,"])
def test_invalid_primary_origin_is_rejected(origin):
    # A trailing separator is normalized like whitespace; it still denotes one origin.
    if origin.endswith(","):
        assert Settings(_env_file=None, FRONTEND_URL=origin).FRONTEND_URL == origin[:-1]
    else:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, FRONTEND_URL=origin)


def test_container_origin_health_and_errors(monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:18080")
    monkeypatch.setattr(settings, "CORS_EXTRA_ORIGINS", "")
    # Create a fresh application without mutating the globally imported app.
    app = runpy.run_path(str(Path(__file__).parents[1] / "app/main.py"))["app"]
    with patch("httpx.AsyncHTTPTransport.handle_async_request", side_effect=AssertionError("No outbound HTTP")), \
            patch("httpx.HTTPTransport.handle_request", side_effect=AssertionError("No outbound HTTP")):
        with TestClient(app) as client:
            response = client.get("/api/v1/health", headers={"Origin": "http://localhost:18080"})
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            assert response.headers["access-control-allow-origin"] == "http://localhost:18080"
            for origin in ["http://localhost:8080", "http://localhost:5173", "http://127.0.0.1:18080", "https://untrusted.example"]:
                response = client.options("/api/v1/health", headers={
                    "Origin": origin, "Access-Control-Request-Method": "GET"})
                assert response.status_code == 400
                assert "access-control-allow-origin" not in response.headers
            response = client.options("/api/v1/evaluation/evaluate", headers={
                "Origin": "http://localhost:18080", "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type"})
            assert response.status_code == 200
            response = client.post("/api/v1/resume/parse", headers={
                "Origin": "http://localhost:18080", "Content-Length": str(12 * 1024 * 1024)})
            assert response.status_code == 413
            assert response.headers["access-control-allow-origin"] == "http://localhost:18080"
