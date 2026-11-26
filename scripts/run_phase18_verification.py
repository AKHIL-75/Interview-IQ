"""Reproduce bounded, offline preparation checks and save exact command evidence.

Uses existing installed dependencies. Does not install Docker, start services,
run live inference, or authenticate to Supabase. Run from the repository root:
backend/.venv/Scripts/python.exe scripts/run_phase18_verification.py
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/phase18-docker-evidence"
EVIDENCE.mkdir(exist_ok=True)
results = []
BACKEND_ONLY = "--backend-only" in sys.argv


def run(name, command, cwd=ROOT, env=None):
    if BACKEND_ONLY and name != "backend-regressions":
        return
    if BACKEND_ONLY:
        name += "-final"
    started = time.monotonic()
    result = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    (EVIDENCE / f"{name}.txt").write_text(result.stdout, encoding="utf-8")
    results.append({"name": name, "command": command, "cwd": str(cwd),
                    "exit_code": result.returncode, "seconds": round(time.monotonic() - started, 2),
                    "output": f"{name}.txt"})
    print(f"{name}: exit {result.returncode}; {results[-1]['seconds']} s", flush=True)


offline = os.environ.copy()
offline.update({
    "PYTHONPATH": str(ROOT / "scripts") + os.pathsep + str(ROOT / "backend"),
    "LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "qwen3:4b",
    "OPENROUTER_API_KEY": "", "OPENROUTER_BENCHMARK_ENABLED": "false",
    "AZURE_SPEECH_KEY": "", "AZURE_STT_SPEECH_KEY": "",
    "SUPABASE_URL": "https://example.invalid", "SUPABASE_ANON_KEY": "synthetic-anon",
    "SUPABASE_SERVICE_ROLE_KEY": "", "FRONTEND_URL": "http://localhost:5173",
    "CORS_EXTRA_ORIGINS": "http://127.0.0.1:5173,http://localhost:5174",
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONIOENCODING": "utf-8",
})
for key in list(offline):
    if key.startswith("IIQ_TEST_"):
        del offline[key]
run("python-compilation", [sys.executable, "-m", "compileall", "-q", "backend/app",
                           "backend/docker_healthcheck.py", "backend/tests/test_container_config.py",
                           "scripts/verify_container_prep.py", "scripts/phase18_offline_guard.py"])
tests = ["test_container_config", "test_phase16_security", "test_settings_security",
         "test_phase15_1_hardening", "test_phase15_1_replay", "test_stage3_integrity",
         "test_submission_fix", "test_submission_performance", "test_subject_adaptation",
         "test_azure_stt", "test_audio_security", "test_audio_resources", "test_stt_speech",
         "test_azure_speech", "test_phase15_stt", "test_live_test_config"]
run("backend-regressions", [sys.executable, "-m", "pytest", *[f"tests/{t}.py" for t in tests],
    "-q", "-p", "no:cacheprovider", "-p", "phase18_offline_guard", "--tb=short", "--show-capture=no",
    "--junitxml=" + str(EVIDENCE / ("backend-regressions-final.xml" if BACKEND_ONLY else "backend-regressions.xml"))], ROOT / "backend", offline)
for suite in ("azure_speech_tests", "phase15_1_rendered", "phase16_tests", "phase17_tests",
              "setup_config_tests", "subject_tests"):
    run("frontend-" + suite, ["node", f"scripts/run_{suite}.mjs"], env=offline)
run("frontend-behavior", ["node", "--test", "scripts/test_phase15_1_behavior.mjs",
                           "scripts/test_live_test_config.mjs"], env=offline)
build_env = os.environ.copy()
build_env["VITE_API_BASE_URL"] = "http://localhost:8000/api/v1"
run("frontend-build", [shutil.which("npm.cmd") or shutil.which("npm"), "run", "build"], env=build_env)
run("static-security", [sys.executable, "scripts/verify_container_prep.py"])
docker = shutil.which("docker")
results.append({"name": "docker-availability", "available": docker is not None,
                "status": "Docker found; run documented Docker acceptance separately" if docker else
                "BLOCKED: Docker CLI absent; compose config, image builds, image inspection and startup not executed"})
(EVIDENCE / ("backend-rerun-results.json" if BACKEND_ONLY else "results.json")).write_text(json.dumps(results, indent=2), encoding="utf-8")
print(results[-1]["status"], flush=True)
sys.exit(1 if any(r.get("exit_code", 0) for r in results) else 0)
