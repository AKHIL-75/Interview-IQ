# Interview-IQ

Interview-IQ is an AI-powered mock interview platform. It combines a React
frontend with a FastAPI backend to support adaptive technical and behavioral
interviews, resume and job-description analysis, answer evaluation, interview
reports, and authenticated interview history. Local question generation and
evaluation use Ollama; Azure Speech can optionally provide interviewer audio
and speech-to-text.

## Stack

- React and Vite frontend
- FastAPI backend
- Ollama with `qwen3:4b` for local LLM inference
- Supabase Auth and Postgres persistence with caller JWTs
- Optional Azure Speech TTS and STT
- Docker Compose with Nginx for local container use

## Configuration

The `.env.example`, `.env.docker.example`, `backend/.env.example`, and
`backend/.env.docker.example` files are templates. Copy them to the corresponding
ignored local environment files and replace placeholders; never commit real
`.env` files or credentials.

Required Supabase settings:

- Frontend: `VITE_SUPABASE_URL` and the public `VITE_SUPABASE_ANON_KEY`
- Backend: `SUPABASE_URL` and `SUPABASE_ANON_KEY`

Use the same Supabase project for both sides. The frontend key is public; do not
put a service-role key in frontend configuration. The backend service-role
setting is unused for normal authenticated operations and should remain empty.
This repository contains no Supabase SQL migration or schema source files, so
the Supabase project must already have the schema and row-level security policies
required by the application.

For local inference, run Ollama and make sure `qwen3:4b` is available. The local
backend defaults to `OLLAMA_BASE_URL=http://localhost:11434` and
`OLLAMA_MODEL=qwen3:4b`. Docker Compose connects to the Ollama service on the
host through `host.docker.internal:11434`.

Azure Speech is optional. Leave the values blank to run without speech services.
For interviewer text-to-speech, configure `AZURE_SPEECH_KEY` and
`AZURE_SPEECH_REGION`. Speech-to-text uses a separate Azure Speech resource:
configure `AZURE_STT_SPEECH_KEY` and `AZURE_STT_SPEECH_REGION`; optionally set
`AZURE_STT_ENDPOINT` and `AZURE_STT_LANGUAGE`. Keep all Azure keys in the
backend's ignored environment file.

## Run locally

Start Ollama separately and ensure `qwen3:4b` is present. In one terminal,
configure and start the backend:

```powershell
Copy-Item backend\.env.example backend\.env
Set-Location backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Fill in the Supabase settings in `backend\.env` before using authenticated
features. In another terminal, from the project root:

```powershell
Copy-Item .env.example .env
npm ci
npm run dev
```

Set the frontend Supabase URL and public anon key in `.env`. The Vite development
server is available at `http://localhost:5173`; the API defaults to
`http://localhost:8000/api/v1`.

## Run with Docker Compose

Install Docker Desktop with Compose v2, keep Ollama running on the host, and
ensure its `qwen3:4b` model is available. Create the local Compose configuration:

```powershell
Copy-Item .env.docker.example .env.docker
Copy-Item backend\.env.docker.example backend\.env.docker
```

Set the public Supabase URL and anon key in root `.env.docker`, and the matching
backend Supabase URL and anon key in `backend\.env.docker`. Then run:

```powershell
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker up --build -d
```

Open `http://localhost:18080`. The backend API is published on
`http://localhost:8000`. Azure Speech remains optional and can be configured in
`backend\.env.docker`. For detailed local container prerequisites, configuration,
checks, and troubleshooting, see [docs/DOCKER_LOCAL.md](docs/DOCKER_LOCAL.md).
