"""Offline structural/security checks; NOT a substitute for docker compose config/build.

Run with backend/.venv/Scripts/python.exe scripts/verify_container_prep.py.
Only names/counts are printed. Private local .env values never leave this process.
"""
import base64
import json
import re
from pathlib import Path

import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
backend = compose["services"]["backend"]
frontend = compose["services"]["frontend"]
env = backend["environment"]
args = frontend["build"]["args"]
assert set(compose["services"]) == {"backend", "frontend"}
assert backend["ports"] == ["127.0.0.1:8000:8000"]
assert frontend["ports"] == ["127.0.0.1:18080:8080"]
assert args["VITE_API_BASE_URL"] == "http://localhost:8000/api/v1"
assert env["FRONTEND_URL"] == "http://localhost:18080"
assert set(env["CORS_EXTRA_ORIGINS"].split(",")) == {
    "http://127.0.0.1:18080", "http://localhost:5173", "http://127.0.0.1:5173",
}
assert env["API_V1_PREFIX"] == "/api/v1"
assert env["LLM_PROVIDER"] == "ollama" and env["OLLAMA_MODEL"] == "qwen3:4b"
assert env["OLLAMA_BASE_URL"] == "http://host.docker.internal:11434"
assert backend["extra_hosts"] == ["host.docker.internal:host-gateway"]
assert env["OPENROUTER_API_KEY"] == ""
assert not any(key.startswith("AZURE_") for key in env), "Configure Azure in backend/.env.docker"
assert not any("AZURE_" in key or "SPEECH_KEY" in key for key in args)
assert env["OPENROUTER_BENCHMARK_ENABLED"] == "false"
assert backend["env_file"] == ["./backend/.env.docker"]
assert frontend["depends_on"]["backend"]["condition"] == "service_healthy"
assert set(args) == {"VITE_API_BASE_URL", "VITE_SUPABASE_URL", "VITE_SUPABASE_ANON_KEY"}
for service in (backend, frontend):
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
for filename in ("Dockerfile", "backend/Dockerfile"):
    source = (ROOT / filename).read_text()
    assert "HEALTHCHECK" in source and "USER " in source and "--reload" not in source
    assert not re.search(r"COPY\s+\.\s", source)
for filename in (".dockerignore", "backend/.dockerignore"):
    source = (ROOT / filename).read_text()
    assert "**\n" in source and "**/.env*" in source
nginx = (ROOT / "docker/nginx.conf").read_text()
assert "try_files $uri $uri/ /index.html;" in nginx
assert "listen 8080;" in nginx and "pid /tmp/nginx.pid;" in nginx
print("PASS: YAML parsing and static ports, public API URL, CORS, provider, health/startup and isolation checks")

# Files admitted by the two intentionally narrow build contexts, plus fresh build.
paths = [ROOT / p for p in ("Dockerfile", "backend/Dockerfile", "backend/requirements.txt",
    "backend/docker_healthcheck.py", "docker-compose.yml", "backend/.env.docker.example",
    "package.json", "package-lock.json", "index.html",
    "vite.config.js", "tailwind.config.cjs", "postcss.config.js", "docker/nginx.conf")]
for directory in ("src", "public", "backend/app", "dist"):
    paths += [p for p in (ROOT / directory).rglob("*") if p.is_file()
              and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}
              and not p.name.startswith(".env")]
private_values = set()
for filename in (".env", "backend/.env", ".env.docker", "backend/.env.docker"):
    if (ROOT / filename).exists():
        for key, value in dotenv_values(ROOT / filename).items():
            if (value and len(value) >= 12 and re.search(r"SECRET|PASSWORD|TOKEN|API_KEY|SPEECH_KEY|SERVICE_ROLE", key)
                    and "ANON" not in key and "your-" not in value):
                private_values.add(value.encode())
violations = []
for path in paths:
    blob = path.read_bytes()
    if any(value in blob for value in private_values):
        violations.append(str(path.relative_to(ROOT)))
    if re.search(rb"(?:sk-or-v1-|sb_secret_)[A-Za-z0-9_-]{20,}", blob):
        violations.append(str(path.relative_to(ROOT)))
    for payload in re.findall(rb"eyJ[A-Za-z0-9_-]+\.([A-Za-z0-9_-]+)\.[A-Za-z0-9_-]+", blob):
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload + b"=" * (-len(payload) % 4)))
            if claims.get("role") == "service_role":
                violations.append(str(path.relative_to(ROOT)))
        except (ValueError, UnicodeDecodeError):
            pass
assert not violations, "Private secret detected in: " + ", ".join(sorted(set(violations)))
assert (ROOT / "dist/index.html").is_file(), "Run npm run build first"
bundles = b"\n".join(p.read_bytes() for p in (ROOT / "dist/assets").glob("*.js"))
assert b"http://localhost:8000/api/v1" in bundles
print(f"PASS: {len(paths)} source/build files scanned against {len(private_values)} configured private values and secret/JWT patterns")
print("PASS: built browser API URL matches published backend port")
print("NOT VERIFIED: Docker CLI validation, image contents/history, Linux dependencies, Nginx runtime, container health or host Ollama connectivity")
