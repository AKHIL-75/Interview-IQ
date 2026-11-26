# Phase 18: production-like local containers

This is local preparation, not an AWS deployment. The active LLM is host Ollama
with `qwen3:4b`. OpenRouter remains dormant and its live acceptance is unverified.
See [verification evidence](PHASE18_DOCKER_VERIFICATION.md) for what actually ran.

## What was found and preserved

There were no Dockerfiles, Compose files, or `.dockerignore` files in this checkout.
The root is the React/Vite frontend; `backend/app/main.py` is the FastAPI entry point.
`package-lock.json` is used with npm. No dependency list, lockfile, UI, routes,
scoring, question logic, auth, RLS or database schema was changed.

**Speech discrepancy:** the current source is Azure Speech STT/TTS, not local
faster-whisper. `backend/requirements.txt` contains Azure Speech 1.52.0 and PyAV,
and no faster-whisper; `stt_provider.py` only dispatches to Azure. An old
`STT_PROVIDER` entry in a local environment file is ignored by current Settings.
Adding faster-whisper to a Dockerfile would not restore its implementation.
Azure Speech is optional. Set the TTS and STT resource settings independently in
the ignored backend runtime env file. Check speech separately from container
health.

## Architecture and prerequisites

```text
Browser http://localhost:18080 --> Nginx :8080 --> Vite static files / SPA fallback
Browser http://localhost:8000/api/v1 --> FastAPI :8000
FastAPI --> http://host.docker.internal:11434 --> existing host Ollama qwen3:4b
Browser + FastAPI --> existing Supabase project (Auth / PostgreSQL with caller JWT)
FastAPI --> local CPU MiniLM embeddings; first use may download model from Hugging Face
```

Use Windows with WSL 2 and Docker Desktop configured for **Linux containers** and
Compose v2. Verify `docker version` and `docker compose version` first. Allow disk
and RAM for the ML Python stack plus the separately running Ollama model; start
with 8 GB available to Docker if practical and measure usage with `docker stats`.
This is planning guidance, not a measured minimum. Internet access is needed for
base images, packages, the first MiniLM download, and existing Supabase access.
No local database or Ollama container is created. Docker does not pull an Ollama model.

Ollama must already be running on the host and `ollama list` must include
`qwen3:4b`. Stop any development backend using host port 8000 before starting
Compose. Open **localhost**, not 127.0.0.1, in the browser: CORS is intentionally exact.
Published ports bind only to host loopback and do not publish this app to the LAN.

## Configuration

From the repository root in PowerShell, create local files only if absent:

```powershell
if (!(Test-Path .env.docker)) { Copy-Item .env.docker.example .env.docker }
if (!(Test-Path backend/.env.docker)) { Copy-Item backend/.env.docker.example backend/.env.docker }
```

Edit these two ignored files with the same existing Supabase project URL and public
anon key. Placeholders let configuration be reviewed but cannot authenticate users.
The backend uses caller JWT + anon key and does not require the service-role key.
Never place a service-role key, Azure key, OpenRouter key, password or access token
in frontend variables. The frontend build rejects recognizable secret/service-role
keys, but operators must still supply only public configuration.

| File / owner | Variables | Meaning |
| --- | --- | --- |
| Root `.env.docker` | `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | Required public build inputs. These are visible in the browser bundle. |
| Compose frontend build | `VITE_API_BASE_URL` | Fixed to `http://localhost:8000/api/v1`; `backend:8000` is not resolvable by the browser. |
| Backend `.env.docker` | `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Required for existing auth and persistence. No database migrations. |
| Backend `.env.docker` | `SUPABASE_SERVICE_ROLE_KEY` | Existing setting, unused by current auth/persistence. Leave empty. |
| Compose backend | `FRONTEND_URL`, `CORS_EXTRA_ORIGINS`, `API_V1_PREFIX` | `http://localhost:18080`, empty extra origins, `/api/v1`. |
| Compose backend | `LLM_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Enforced `ollama`, host gateway, `qwen3:4b`. |
| Backend `.env.docker` | `OLLAMA_KEEP_ALIVE`, `OLLAMA_TIMEOUT`, `OLLAMA_NUM_PREDICT`, `OLLAMA_THINK`, `LLM_OPERATION_TIMEOUT_S` | `10m`, `120`, `300`, `false`, `150`; matches inspected local configuration/defaults. |
| Backend optional | `APP_NAME`, `APP_VERSION` | Existing metadata defaults. |
| Compose backend | `PERFORMANCE_DIAGNOSTICS` | Disabled; retain sanitized existing error handling. |
| Dormant backend only | `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_PRIMARY_MODEL`, `OPENROUTER_FALLBACK_MODELS`, `OPENROUTER_TIMEOUT_S`, `OPENROUTER_BENCHMARK_ENABLED`, `OPENROUTER_ZDR`, `OPENROUTER_FREE_ONLY` | Existing settings retained; Compose clears key and disables benchmark, provider remains Ollama. Do not populate for this phase. |
| Backend `.env.docker` | `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` | Optional TTS. Use the key and region for the existing TTS resource. |
| Backend `.env.docker` | `AZURE_STT_SPEECH_KEY`, `AZURE_STT_SPEECH_REGION`, `AZURE_STT_ENDPOINT`, `AZURE_STT_LANGUAGE`, `AZURE_STT_TIMEOUT_S`, `AZURE_STT_MAX_AUDIO_S`, `AZURE_STT_MAX_CONCURRENCY`, `AZURE_STT_PHRASE_LIST` | Optional STT. Use the existing STT resource settings. When the endpoint is empty, the application uses the regional endpoint. |
| Image runtime | `HF_HOME`, `PYTHONUNBUFFERED`, `PYTHONDONTWRITEBYTECODE`, `PIP_NO_CACHE_DIR` | Writable persistent embedding cache and normal container Python operation. |

Compose's `environment` entries override backend `env_file` entries. Root
`--env-file .env.docker` is for Compose interpolation; `backend/.env.docker` is
injected at runtime. Neither file is copied into an image. Avoid bare
`docker compose config` in shared logs because it expands runtime secrets; use `config --quiet`.
People with Docker daemon access can inspect runtime environment variables, so
this is a local environment injection mechanism, not a hosted secret manager.

After changing Azure settings on an existing stack, apply them to the backend
with `docker compose --env-file .env.docker up -d --no-deps --no-build backend`.

Vite configuration is embedded at **build time**. Changing public values requires
rebuilding the frontend, not only restarting it. Native development still uses
the existing root/backend `.env` and `npm run dev`. CORS now uses `FRONTEND_URL`
plus `CORS_EXTRA_ORIGINS`; the old 5173/127.0.0.1 and localhost:5174 aliases remain
the development defaults. Compose clears the aliases to allow only host port 18080.
For Supabase auth callbacks/recovery, the project's allowed redirect URLs must
include `http://localhost:18080/auth/callback` and
`http://localhost:18080/reset-password` (see
[existing auth setup](PHASE17_AUTH_SETUP.md)). No Supabase settings were changed here.

## Build and run

```powershell
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker build backend
docker compose --env-file .env.docker build frontend
docker compose --env-file .env.docker up -d --wait --wait-timeout 180
docker compose --env-file .env.docker ps
```

Browse `http://localhost:18080`. A frontend health dependency waits for backend
HTTP liveness. It does **not** prove Supabase, Ollama, model availability, speech,
or an authenticated interview is ready. It is startup ordering, not a continuous
dependency supervisor; an unhealthy container is not automatically restarted
solely because its health probe failed.

```powershell
docker compose --env-file .env.docker logs --tail 100 backend frontend
Invoke-RestMethod http://localhost:8000/api/v1/health
curl.exe -f http://localhost:18080/healthz
curl.exe -I http://localhost:18080/login
curl.exe -I http://localhost:18080/dashboard
curl.exe -i -X OPTIONS http://localhost:8000/api/v1/health -H "Origin: http://localhost:18080" -H "Access-Control-Request-Method: GET"
docker compose --env-file .env.docker exec backend python -c "from app.core.config import settings; print(settings.LLM_PROVIDER, settings.OLLAMA_MODEL, settings.OLLAMA_BASE_URL)"
docker compose --env-file .env.docker exec backend python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://host.docker.internal:11434/api/tags',timeout=5)); print('qwen3:4b present:',any(m['name']=='qwen3:4b' for m in d['models']))"
```

These checks do not generate text or write to Supabase. Confirm `/login` and
`/dashboard` return the same SPA entry document as `/`, then refresh them in a
browser; a protected route may correctly redirect to login. Inspect browser
Network: API requests must target `localhost:8000/api/v1`. A missing asset under
`/assets/` should return 404 rather than HTML. A different Origin should get no
`Access-Control-Allow-Origin` header. Do not use AI test/generation routes as health probes.

For image review (after actual builds), `docker compose --env-file .env.docker images`
identifies the images. Inspect their `Config.User` and `Config.Env`, and run
`docker image history --no-trunc <image-id>` locally. Verify runtime secrets are
absent from image configuration/history and `/app/.env`, `/app/.env.docker`,
`/app/node_modules` (frontend runtime), test uploads and source env files are absent.
Review exported layers with an approved secret scanner before any registry push;
no image-layer scan has been claimed in this phase without Docker.

## Stop and clean up

```powershell
docker compose --env-file .env.docker stop
docker compose --env-file .env.docker down
```

`stop` retains containers; `down` removes this stack's containers and network but
keeps the named embedding cache. Only when intentionally discarding downloaded
MiniLM cache, use `docker compose --env-file .env.docker down --volumes`.
It does not delete Supabase records or the host's Ollama models. Do not use broad
system pruning to clean this stack. Local env files remain private on disk.

## Troubleshooting and trade-offs

- **Frontend API/network:** container DNS names work between containers, not in
  the browser. Port 8000 must be free and mapped as shown. A remote browser's
  localhost refers to that remote machine; this setup supports the local browser.
- **CORS:** use `http://localhost:18080` exactly, with no trailing slash in config.
  If you intentionally change the origin/port, update both Compose mappings and
  `FRONTEND_URL`, and rebuild if the API URL changes. Wildcard CORS is not used.
- **Ollama connection refused:** test `/api/tags` from the backend container,
  not only from Windows. Docker Desktop provides `host.docker.internal`; Linux
  Engine uses the included `host-gateway` mapping. Linux commonly also needs Ollama
  listening on the bridge-facing host interface. If a loopback-only listener is
  unreachable, configure `OLLAMA_HOST` for a reachable interface and restart
  Ollama; `0.0.0.0:11434` is a broad fallback only with firewall access restricted
  to local/Docker traffic. Do not expose unauthenticated Ollama to the LAN or internet.
  DNS mapping alone does not open a listener or bypass firewall rules. See
  [Docker host networking](https://docs.docker.com/desktop/features/networking/networking-how-tos/)
  and [Ollama host configuration](https://docs.ollama.com/faq).
- **Model missing:** verify `qwen3:4b` with `ollama list`; setup never downloads it
  automatically. A healthy backend only proves the HTTP process can answer.
- **Missing config/auth:** ensure both local env files exist and contain the same
  Supabase project. Blank public build variables fail Compose expansion. Wrong
  placeholder values still require correction even if `/health` returns 200.
- **ML image size:** Debian slim retains glibc wheels. CPU-only PyTorch avoids
  CUDA runtime packages; Sentence Transformers and its scientific dependencies
  still make the backend much larger than Nginx. Expect potentially gigabytes of
  dependencies/build storage, not a tiny Python image; exact size is unmeasured.
  CPU is the explicit embedding compute choice for this stack; model identity and
  inference code stay unchanged. Ollama can still use the Windows GPU separately.
  [PyTorch supports CPU installation](https://pytorch.org/get-started/locally/).
- **Cold starts/cache:** MiniLM loads lazily and can download on first semantic
  request. Its named cache is owned by UID 10001 on a fresh volume. A reused cache
  with incorrect ownership needs operator repair for that volume; do not run the
  app as root as a workaround. No model is fetched by the HTTP health check.
- **Native dependencies:** PyAV wheels bundle FFmpeg libraries; no ffmpeg CLI is
  used by the inspected decoder. `libgomp1` supports CPU native computation;
  `libasound2`, `libssl3` and CA certificates support the retained Azure SDK on
  Debian 12 ([SDK platform requirements](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/quickstarts/setup-platform)).
  Faster-whisper would add CTranslate2 and model storage if restored later, and
  GPU variants require a deliberate CUDA/cuDNN design; it is not secretly removed here.
- **Resource behavior:** one Uvicorn worker retains process-local request admission
  and rate-limit semantics without multiplying model memory. Native STT hard-timeout
  limitations documented in `AUDIO_TRANSCRIBE_SECURITY.md` remain. No GPU passthrough.
- **Reproducibility:** base images use version tags, not floating `latest`, but are
  not digest-locked. Existing Python ranges/transitive packages remain unlocked;
  `npm ci` follows the existing lock. Review current security patches, lock tested
  Linux dependencies and image digests, and scan images before genuine hosting.
  Local Python 3.13 tests do not establish Linux Python 3.12 wheel compatibility.

## Before any genuine hosted deployment

An AWS-hosted backend cannot reach Ollama on the developer's Windows laptop via
`localhost` or `host.docker.internal`: those names refer to the hosted container
or its hosted machine. A later deployment needs a separately designed, reachable,
secured inference service or another explicitly approved architecture. **Do not
silently replace Ollama with a cloud LLM.**

Close the Docker build/start gates first. Then separately design HTTPS/domain and
browser API build URLs, exact CORS, trusted proxy handling, Supabase redirect URLs,
runtime secret management, resource sizing, shared rate limits if scaling beyond
one process, model/cache storage, security patching/scans, monitoring/backups and
cost controls. Resolve the current speech architecture discrepancy before claiming
local speech support. No AWS resources, registry push, public deployment, paid
inference, credentials or Supabase schema/settings were created or changed here.
