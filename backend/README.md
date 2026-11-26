# Interview-IQ Backend

FastAPI backend for **Interview-IQ**, an AI-powered adaptive mock interview platform. The backend provides intelligent interview orchestration, candidate evaluation, Azure speech-to-text processing, and user-isolated data persistence.

---

> [!WARNING]
> **CRITICAL ENVIRONMENT CONFIGURATION NOTICE**
> The `.env.example` file is **only a template** containing placeholders. Running `copy .env.example .env` is only the first setup step. You **MUST** edit `backend/.env` and replace all placeholder values with your actual project credentials (such as your Supabase project URL and anon key) before starting the server.
>
> - **NEVER commit `backend/.env` to Git.**
> - **NEVER place service-role keys, API keys, JWT secrets, or passwords in source code.**
> - **NEVER expose backend secrets to the frontend.**

---

## 1. Project Overview

Interview-IQ is designed to simulate realistic technical and behavioral interviews with dynamic, context-aware follow-up questioning and deterministic multi-dimensional grading.

### Key Capabilities

- **Authentication & Authorization**: Integrated with Supabase GoTrue; validates JWT Bearer tokens and extracts authenticated user identities.
- **Resume Processing & Parsing**: Ingests PDF and DOCX files, extracts text, and parses structured candidate profiles (skills, experience, projects) using local LLM inference.
- **Job Description Processing**: Normalizes job specifications and extracts structured role profiles, core requirements, and preferred competencies.
- **Semantic Matching & Gap Analysis**: Evaluates candidate fit against job requirements using local Sentence Transformers (`all-MiniLM-L6-v2`) embeddings, vector cosine similarity, and technology domain guards (e.g., distinguishing Java from JavaScript).
- **Personalized & Adaptive Question Generation**: Generates targeted interview plans and dynamically produces follow-up or challenge questions based on candidate performance.
- **Answer Evaluation Engine**: Multi-dimensional grading across Technical Accuracy, Relevance, Depth, and Clarity with structured feedback and model answers.
- **Authoritative Performance Reports**: Calculates overall scores, letter grades, topic performance breakdowns, and adaptive summaries.
- **Interview History & Dashboard Analytics**: Aggregates interview history, performance trends, and candidate analytics isolated per user.
- **Azure Speech-to-Text (STT)**: Final live Azure transcripts are submitted unchanged; recorded audio can be transcribed by the Azure-only upload endpoint when no final live transcript exists.
- **Local LLM Inference**: Powered by local `qwen3:4b` executed via Ollama.
- **PostgreSQL Persistence with RLS**: All user records (resumes, job profiles, sessions, questions, answers, reports) are stored in Supabase under PostgreSQL Row Level Security (RLS).

---

## 2. Requirements

Before running the backend, ensure the following prerequisites are installed:

- **Python 3.10+**: Verify with:
  ```bash
  python --version
  ```
- **Ollama**: Running locally with the `qwen3:4b` model pulled.
- **Supabase Project**: An active Supabase instance with database migrations applied.

> [!NOTE]
> The Node.js React frontend is developed and hosted separately. Node.js is not required to run or test the Python backend service.

---

## 3. Windows Setup

Follow these steps from a PowerShell or Command Prompt terminal:

### Step 1: Create a Virtual Environment

```bash
cd backend
python -m venv .venv
```

### Step 2: Activate the Virtual Environment

```bash
.venv\Scripts\activate
```

Upon activation, your terminal prompt will display `(.venv)`.

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure the Environment File

```bash
copy .env.example .env
```

Open `backend/.env` in your text editor and configure your actual settings. Do **not** leave dummy credentials in place.

---

## 4. Environment Variables

The backend uses `pydantic-settings` to load and validate environment variables from `backend/.env`.

### Variable Reference

| Variable | Classification | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `APP_NAME` | Development Default | `Interview-IQ Backend` | Application name used in documentation and logs |
| `APP_VERSION` | Development Default | `1.0.0` | API service version |
| `FRONTEND_URL` | Development Default | `http://localhost:5173` | Allowed CORS origin for local React development |
| `API_V1_PREFIX` | Development Default | `/api/v1` | URL prefix for v1 API routers |
| `OLLAMA_BASE_URL` | Development Default | `http://localhost:11434` | HTTP address of your local Ollama server |
| `OLLAMA_MODEL` | Development Default | `qwen3:4b` | Ollama model tag used for JSON inference |
| `OLLAMA_KEEP_ALIVE` | Development Default | `10m` | Duration to keep the model loaded in Ollama memory |
| `OLLAMA_TIMEOUT` | Development Default | `120.0` | Maximum timeout in seconds for LLM generation |
| `OLLAMA_NUM_PREDICT` | Development Default | `300` | Maximum tokens to generate per inference call |
| `OLLAMA_THINK` | Development Default | `false` | Enable/disable Qwen3 reasoning mode |
| `SUPABASE_URL` | **Required** | `""` | Supabase project URL (e.g., `https://your-project.supabase.co`) |
| `SUPABASE_ANON_KEY` | **Required** | `""` | Supabase public/anon publishable key for token verification & PostgREST queries |
| `SUPABASE_SERVICE_ROLE_KEY` | Optional Fallback | `""` | Optional service key fallback. **Not required** for normal authenticated user operations |

### Example `.env` Configuration

```env
# Application Settings
APP_NAME=Interview-IQ Backend
APP_VERSION=1.0.0
FRONTEND_URL=http://localhost:5173
API_V1_PREFIX=/api/v1

# Ollama / LLM Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:4b
OLLAMA_KEEP_ALIVE=10m
OLLAMA_TIMEOUT=120.0
OLLAMA_NUM_PREDICT=300
OLLAMA_THINK=false

# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-or-publishable-key
SUPABASE_SERVICE_ROLE_KEY=

# Speech-to-Text (separate Azure Speech resource)
AZURE_STT_SPEECH_KEY=
AZURE_STT_SPEECH_REGION=
AZURE_STT_ENDPOINT=
AZURE_STT_LANGUAGE=en-IN
AZURE_STT_TIMEOUT_S=630
AZURE_STT_MAX_AUDIO_S=600
AZURE_STT_MAX_CONCURRENCY=1
AZURE_STT_PHRASE_LIST=
```

---

## 5. Ollama Configuration

Interview-IQ runs LLM inference locally via Ollama to ensure data privacy and offline capability.

### 1. Verify Ollama is Running

Ensure the Ollama background service is running:

```bash
ollama list
```

If Ollama is not active, start it in a separate terminal:

```bash
ollama serve
```

### 2. Pull the Required Model

Pull the Qwen3 4B model configured by the backend:

```bash
ollama pull qwen3:4b
```

### 3. Verify Connection via Backend

You can test that the backend connects properly to Ollama using the test endpoint:

```bash
curl -X POST http://localhost:8000/api/v1/ai/test -H "Content-Type: application/json" -d "{}"
```

---

## 6. Supabase Configuration

Interview-IQ utilizes Supabase for authentication and PostgreSQL data storage with strict tenant isolation.

### Architectural Flow

```
Frontend (User Session)
  │
  ├─► Sends request with "Authorization: Bearer <access_token>"
  ▼
FastAPI Backend
  │
  ├─► Validates JWT via Supabase GoTrue (/auth/v1/user)
  ├─► Resolves authenticated user UUID
  ▼
Supabase PostgREST
  │
  ├─► Executes queries forwarding Bearer token + anon apikey
  ▼
PostgreSQL Database
  └─► Row Level Security (RLS) restricts rows to auth.uid()
```

- **Row Level Security (RLS)**: Enforces that users can only read, create, or update their own resumes, job descriptions, sessions, questions, answers, and reports.
- **No Service-Role Key Needed**: Standard authenticated operations rely solely on the user's validated JWT and the public anon key. The backend does not bypass RLS.
- **Zero Frontend Secret Exposure**: The frontend only receives publishable anon credentials; no database credentials or service-role keys are exposed to clients.

---

## 7. Running the Backend

Ensure your virtual environment is activated, then launch the FastAPI server with Uvicorn:

```bash
uvicorn app.main:app --reload --port 8000
```

### Access URLs

- **API Base**: [http://localhost:8000](http://localhost:8000)
- **Interactive Swagger Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc API Reference**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Service Health Check**: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

---

## 8. API Endpoints

All application routes are prefixed with `/api/v1` (except the root endpoint).

### 1. System & Health

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | Root endpoint confirming backend service status | None |
| `GET` | `/api/v1/health` | Health check returning status and version | None |
| `POST` | `/api/v1/ai/test` | Verifies Ollama connectivity and Qwen3 JSON inference | None |

### 2. Resume Processing

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/resume/parse` | Ingests PDF/DOCX file and extracts structured `CandidateProfile`. Persists to `resumes` if authenticated. | Optional |

### 3. Job Description Processing

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/job/parse` | Ingests job description text and extracts structured `JobProfile`. Persists to `job_descriptions` if authenticated. | Optional |

### 4. Semantic Analysis

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/analysis/match` | Runs embedding cosine similarity between candidate and job profile to compute match score and skill gaps. | None |

### 5. Interview Management & Question Generation

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/interview/start` | Creates interview plan, stage progression, and returns Question 1. Persists session to Supabase if authenticated. | Optional |
| `POST` | `/api/v1/interview/generate-questions` | Generates a full question set tailored to candidate profile, job description, difficulty, and category. | None |
| `POST` | `/api/v1/interview/next-question` | Evaluates previous response, determines next adaptive state, and dynamically generates follow-up or challenge question. | Optional |

### 6. Answer Evaluation

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/evaluation/evaluate` | Evaluates candidate answer across Technical Accuracy, Relevance, Depth, and Clarity with structured feedback. | Optional |

### 7. Performance Reports

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/interview/report` | Compiles and persists authoritative report to Supabase `interview_reports` and marks session completed. | Optional |
| `POST` | `/api/v1/interview/generate-report` | Generates deterministic final report without requiring database persistence. | Optional |
| `GET` | `/api/v1/interview/report/{report_id_or_session_id}` | Retrieves a specific performance report by report UUID or session ID under RLS isolation. | **Required** |

### 8. History & Analytics

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/interview/history` | Retrieves authenticated user's past interview sessions and reports. | **Required** |
| `GET` | `/api/v1/interview/analytics` | Computes live dashboard metrics, score distributions, and performance trends strictly for the authenticated user. | **Required** |

### 9. Audio & Speech-to-Text

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/audio/transcribe` | Transcribes browser audio using Azure Speech after Supabase authentication. Temporary files are removed in cleanup. | **Required** |

---

## 9. Voice & Audio Pipeline

Voice/Camera live recognition uses the short-lived token from the authenticated `/speech/stt-token` endpoint. The browser submits finalized Azure text unchanged; the report preserves that submitted answer separately from evaluation feedback.

When live final text is unavailable, MediaRecorder audio is posted to `/audio/transcribe`. The backend validates MIME and the 25 MB upload limit, decodes supported formats with PyAV to 16 kHz mono PCM, and sends PCM to Azure Speech. Temporary files are removed in `finally`. The recording limit remains 600 seconds. The cooperative processing deadline is `min(AZURE_STT_TIMEOUT_S, 630, decoded_duration_seconds + 30)` seconds from admission, including queue wait. Before duration is known it is capped at `min(AZURE_STT_TIMEOUT_S, 630)`. The browser upload timeout is 660 seconds, providing a 30-second transport/auth margin over the maximum processing budget; slow uploads and deployment proxies require their own limits.

Set the STT resource credentials through backend settings, separately from TTS. No Azure key is sent to the browser. Missing STT configuration produces a controlled error; there is no local ASR fallback. Generic recording, audio diagnostics and Text mode remain available.

Audio uploads require the existing `get_current_auth` dependency before multipart parsing, spooling, route temporary files, decoding or Azure work. Its validated result is cached only on that request. Invalid/expired/missing bearer credentials receive the existing sanitized authentication errors. No session/question fields were added.

Decoder accumulation is capped during resampling at the smaller of 600 seconds and `AZURE_STT_MAX_AUDIO_S`; statistics and PCM conversion use fixed-size blocks. Per process, admission allows at most `2 * AZURE_STT_MAX_CONCURRENCY` jobs (default one execution slot plus one waiting job); excess requests receive sanitized 429 with Retry-After. Existing per-IP request limits remain. Native PyAV/SDK calls cannot be forcibly interrupted by these cooperative checks; a stuck call retains its slot/admission and its file until safe cleanup. Strict native wall-clock enforcement would require separately reviewed process isolation. See `../docs/AUDIO_TRANSCRIBE_SECURITY.md` for evidence and deployment checks.

---

## 10. Camera Mode

Interview-IQ provides an optional Camera Mode to simulate realistic video interview conditions:

- **Local Preview Only**: The camera stream is rendered directly inside the candidate's browser via the HTML5 `<video>` element and WebRTC `getUserMedia()`.
- **No Video Upload**: The backend does **not** receive, stream, record, or store webcam video.
- **No Biometric Surveillance**: The platform does **not** perform facial recognition, emotion detection, eye tracking, identity verification, or AI proctoring.

---

## 11. Testing

The backend includes a comprehensive suite of unit, integration, and regression tests.

### Running Regression Suites

Run the full regression test runner to verify all modules:

```bash
python tests/run_all_regressions.py
```

### Running Individual Test Suites

You can execute targeted test files directly:

```bash
# Speech-to-Text unit tests (mocked Azure recognition, MIME checks, real synthetic WAV decoding)
python tests/test_phase15_stt.py

# End-to-end Voice & Audio integration pipeline
python tests/verify_phase15_integration.py

# Resume parsing & schema validation
python tests/test_phase4.py

# Job description extraction
python tests/test_phase5.py

# Semantic matching & taxonomy guards
python tests/test_phase6.py

# Personalized question generation
python tests/test_phase7.py

# Answer evaluation engine
python tests/test_phase10.py

# Supabase persistence & RLS isolation
python tests/test_phase11_persistence.py

# User interview history & analytics
python tests/test_phase13_history_analytics.py

# Final performance report generation
python tests/test_phase14_report_generation.py
```

> [!NOTE]
> If `pytest` is installed in your Python environment, you can also run suites via:
> ```bash
> pytest tests/
> ```

---

## 12. Project Structure

The backend is organized into modular layers separating API routing, business logic, prompt engineering, and persistence:

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI application entry point, CORS middleware, request logging
│   ├── core/
│   │   ├── __init__.py
│   │   ├── auth.py              # Supabase JWT validation dependencies (get_current_auth, get_optional_auth)
│   │   └── config.py            # Pydantic-settings configuration loading from environment & .env
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── api.py            # Central v1 router mounting all endpoint sub-routers
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           ├── health.py     # GET /health service check
│   │           ├── ai_test.py    # POST /ai/test Ollama/Qwen3 verification
│   │           ├── resume.py     # POST /resume/parse upload & extraction
│   │           ├── job.py        # POST /job/parse job description normalization
│   │           ├── analysis.py   # POST /analysis/match semantic embedding similarity
│   │           ├── interview.py  # Session start, adaptive follow-ups, reports, history, analytics
│   │           ├── evaluation.py # POST /evaluation/evaluate 4-dimension answer grading
│   │           └── audio.py      # POST /audio/transcribe Azure Speech-to-Text
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── adaptive_prompts.py   # Follow-up and challenge generation prompts
│   │   ├── ai_test.py            # AI connectivity verification prompt
│   │   ├── evaluation_prompts.py # Answer evaluation scoring prompt
│   │   ├── job_prompts.py        # Job description extraction prompt
│   │   ├── question_prompts.py   # Personalized question generation prompts
│   │   ├── resume.py             # Base resume prompt templates
│   │   └── resume_prompts.py     # Candidate profile extraction prompt
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── adaptive.py          # Schemas for session plan, stage progression, adaptive actions
│   │   ├── analysis.py          # Schemas for match analysis request/response
│   │   ├── evaluation.py        # Schemas for answer evaluation and feedback
│   │   ├── interview.py         # Schemas for question generation requests
│   │   ├── job.py               # Schemas for job profiles and competencies
│   │   └── resume.py            # Schemas for candidate profiles and education/projects
│   └── services/
│       ├── __init__.py
│       ├── adaptive_interviewer.py # Adaptive decision engine (follow-up/challenge/advance)
│       ├── evaluator.py            # Answer evaluation orchestration & deterministic score merging
│       ├── jd_parser.py            # Job text normalization & LLM extraction
│       ├── llm_service.py          # Centralized Ollama HTTP client & robust JSON extraction
│       ├── persistence_service.py  # Supabase PostgREST client with user JWT & RLS compliance
│       ├── question_generator.py   # Initial personalized question generator
│       ├── report_generator.py     # Authoritative report compiler, grading, and metrics
│       ├── resume_parser.py        # PDF/DOCX binary extraction & text validation
│       ├── semantic_matcher.py     # SentenceTransformers embedding computation & tech guards
│       ├── skill_taxonomy.py       # Technical taxonomy categories & collision prevention rules
│       └── stt_service.py          # Shared transcription errors and quality warnings
├── tests/                          # Automated unit, integration, and regression test suites
├── benchmark_adaptive_latency.py   # Benchmarking script for inference and decision latency
├── requirements.txt                # Python dependencies
├── .env.example                    # Template environment file with placeholders
└── README.md                       # Backend technical documentation
```

---

## 13. Security

- **JWT Validation**: Authenticated requests require an `Authorization: Bearer <token>` header. Tokens are verified directly against Supabase GoTrue (`/auth/v1/user`).
- **PostgreSQL Row Level Security (RLS)**: Database operations are routed through Supabase PostgREST using the user's validated JWT. PostgreSQL guarantees data isolation such that users cannot access records belonging to other users.
- **No Token Logging**: Access tokens and sensitive authorization credentials are never written to server logs or traces.
- **Ephemeral Audio**: Audio recordings processed via `/api/v1/audio/transcribe` are saved temporarily and deleted immediately once transcription finishes.
- **No Video Data**: Webcam video is processed locally in the client browser; no video streams reach the backend.
- **No Secrets in Source**: `.env` is listed in `.gitignore` to prevent sensitive credentials from ever being committed to source control.

---

## 14. Troubleshooting

### 1. Backend Won't Start
- **Cause**: Incompatible Python version or unactivated virtual environment.
- **Fix**: Verify Python version (`python --version` should be 3.10+) and ensure your virtual environment is active (`.venv\Scripts\activate`). Reinstall dependencies with `pip install -r requirements.txt`.

### 2. Port 8000 Already in Use
- **Cause**: Another process or background instance of Uvicorn is occupying port 8000.
- **Fix**: Start the server on an alternate port:
  ```bash
  uvicorn app.main:app --reload --port 8001
  ```
  *(Remember to update `VITE_API_URL` or frontend proxy accordingly if changing the port).*

### 3. Supabase 401 Unauthorized
- **Cause**: The incoming request does not contain a valid `Authorization: Bearer <token>` header, the Supabase access token has expired, or `SUPABASE_URL` / `SUPABASE_ANON_KEY` in `.env` is misconfigured.
- **Fix**: Check that the frontend session is active and supplying the Bearer token. Confirm your Supabase credentials in `backend/.env`. **Never disable authentication or make protected routes public to resolve 401 errors.**

### 4. Missing Authentication Token
- **Cause**: An endpoint requiring user identity (such as `/history` or `/analytics`) was called without an `Authorization` header.
- **Fix**: Ensure the frontend client attaches the user's Supabase session access token via `Authorization: Bearer <token>`.

### 5. Ollama Unavailable (503 Service Unavailable)
- **Cause**: The Ollama service is not running locally.
- **Fix**: Launch Ollama by executing `ollama serve` in a terminal window, or start the Ollama desktop application. Verify with `ollama list`.

### 6. Ollama Model Missing (503 Service Unavailable)
- **Cause**: The model specified by `OLLAMA_MODEL` (default: `qwen3:4b`) has not been pulled.
- **Fix**: Pull the model by running:
  ```bash
  ollama pull qwen3:4b
  ```

### 7. Resume Parsing or Generation Failure
- **Cause**: The uploaded file contains no extractable text (e.g., scanned image PDF without OCR) or exceeds size limits.
- **Fix**: Ensure uploaded resumes are text-based PDFs or DOCX files under the upload size limit (10MB).

### 8. Audio Transcription Failure (415 or 503)
- **Cause**: Unsupported audio format (415) or Azure Speech configuration/SDK failure (503).
- **Fix**: Ensure audio is recorded in a supported container (WebM, OGG, WAV, MP3, FLAC, MP4). Verify that `azure-cognitiveservices-speech`, `numpy` and `av` dependencies are installed properly from `requirements.txt`.

### 9. CORS Errors
- **Cause**: The frontend is running on a port or origin not listed in CORS configuration.
- **Fix**: Verify `FRONTEND_URL` in `backend/.env`. By default, `app/main.py` permits requests from `http://localhost:5173` and `http://localhost:5174`.

### 10. Environment Variables Not Loaded
- **Cause**: The `.env` file does not exist in the `backend/` directory or was created with invalid syntax.
- **Fix**: Ensure you copied `.env.example` to `backend/.env` (in the same directory as `requirements.txt`) and that there are no unquoted special characters breaking syntax.
