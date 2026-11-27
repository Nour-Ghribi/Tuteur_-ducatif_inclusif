# Tuteur éducatif inclusif

**GenAI · Reinforcement Learning · MLOps**

An inclusive educational tutor that generates personalised learning activities,
adapts to each student's pace and needs, and runs a full MLOps pipeline.

[![CI](https://github.com/Nour-Ghribi/Tuteur_-ducatif_inclusif/actions/workflows/ci.yml/badge.svg?branch=integration/main)](https://github.com/Nour-Ghribi/Tuteur_-ducatif_inclusif/actions/workflows/ci.yml)

---

## Table of contents

1. [Architecture overview](#architecture-overview)
2. [Repository structure](#repository-structure)
3. [Quick start (local)](#quick-start-local)
4. [Environment variables](#environment-variables)
5. [Running tests](#running-tests)
6. [Cloud deployment](#cloud-deployment)
7. [Feature map](#feature-map)
8. [Student history fixtures](#student-history-fixtures)
9. [Contributing](#contributing)

---

## Architecture overview

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (React/Vite)              │
│  OnboardingPage · StudentPage · ProgressPage         │
│  TeacherPage · ParentPage · FR/AR/EN · RTL           │
└─────────────────────┬───────────────────────────────-┘
                      │  /api/v1  (Bearer token)
┌─────────────────────▼────────────────────────────────┐
│          FastAPI — app/main.py (MLOps scaffold)       │
│  /health · /ready · /metrics · /artifacts/validated  │
│  mounts ──► create_tutor_router() [agentic layer]    │
└──────┬──────────────┬────────────────────────────────-┘
       │              │
┌──────▼──────┐  ┌────▼────────────────────────────────┐
│  RL service │  │   backend/agentic (LangGraph)         │
│  LinUCB     │  │   intake → plan → retrieve → generate │
│  POST /v1/  │  │   → verify → recommend → audio/video │
│  recommend  │  │   → finalize                          │
└─────────────┘  └────────────┬───────────────────────--┘
                               │  TUTOR_GENAI_BACKEND=tuteur
                    ┌──────────▼──────────────────────────┐
                    │  src/tuteur (GenAI+RAG+RL library)   │
                    │  Tutor.ask/quiz/remediate             │
                    │  VectorStore (ChromaDB + BM25)        │
                    │  LLM (any OpenAI-compatible API)      │
                    │  AdaptiveTutorService (LinUCB)        │
                    └─────────────────────────────────────-┘
                    
Infrastructure: MLflow · Airflow · Prometheus · Grafana · Docker Compose
```

---

## Repository structure

```
.
├── src/tuteur/              GenAI+RAG+RL library
│   ├── generation.py        Tutor class (ask/quiz/remediate)
│   ├── vectorstore.py       ChromaDB + BM25 hybrid search
│   ├── ingestion.py         PDF/MD/TXT extraction + VLM image description
│   ├── chunking.py          Text + image-caption chunks
│   ├── vision.py            VLM describer (Ollama/Gemini/OpenAI)
│   ├── prompts/             Versioned YAML prompts (FR/AR/EN + school_level)
│   └── adaptive/            LinUCB policy + SQLite ledger + engagement + badges
│
├── backend/
│   ├── agentic/             LangGraph orchestration layer
│   │   └── src/tutor_agentic/
│   │       ├── graph/       LangGraph nodes + builder
│   │       ├── profiles/    Student profile store + onboarding API
│   │       ├── reporting/   Parent report + PDF export
│   │       ├── audio/       TTS adapter + text extractor
│   │       ├── video/       Slide script + Pillow/moviepy renderer
│   │       └── engagement/  EngagementService bridge
│   └── rl/                  LinUCB HTTP microservice
│
├── app/                     MLOps FastAPI scaffold (mounts agentic router)
├── orchestration/           Airflow DAGs (RAG, RL, evaluation pipelines)
├── monitoring/              Prometheus · Grafana · Evidently · OpenTelemetry
├── frontend/                React/Vite app (FR/AR/EN, RTL, accessibility)
├── tests/                   MLOps + tuteur library tests
│   └── tuteur/              Unit tests for src/tuteur (chunking, vision, video…)
├── data/
│   ├── raw/                 Sample course (photosynthèse.md)
│   └── fixtures/students/   Synthetic student history for demo + warm-start
├── compose.yaml             Full Docker Compose (api + rl + mlflow + airflow + grafana)
└── .github/workflows/ci.yml CI: ruff + pytest + docker build
```

---

## Quick start (local)

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker + Docker Compose (for the full stack)

### 1. Clone and configure

```bash
git clone https://github.com/Nour-Ghribi/Tuteur_-ducatif_inclusif.git
cd Tuteur_-ducatif_inclusif
git checkout integration/main
cp .env.example .env
# Edit .env — set your LLM provider (Ollama, Groq, Gemini, OpenAI...)
```

### 2. Install the tuteur library

```bash
pip install -e .
# Optional: install evaluation dependencies
pip install -e ".[eval]"
```

### 3. Install the agentic layer

```bash
cd backend/agentic
pip install -e ".[dev]"
cd ../..
```

### 4. Ingest a course

```bash
# Without VLM (text only)
tuteur ingest data/raw/photosynthese.md

# With VLM image description (set VISION_MODEL in .env first)
tuteur ingest data/raw/photosynthese.md
```

### 5. Start the full stack

```bash
docker compose up
```

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| RL service | http://localhost:8001 |
| MLflow | http://localhost:5000 |
| Airflow | http://localhost:8080 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

### 6. Start the frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

The first time a student opens the app, the **onboarding wizard** walks them
through age group, school level, special needs (dyslexia/ADHD/autism/…),
vision, hearing, and language preference.

---

## Environment variables

See `.env.example` for the full reference. Key variables:

| Variable | Default | Description |
|---|---|---|
| `TUTOR_GENAI_BACKEND` | `mock` | `mock` / `tuteur` (in-process) / `http` |
| `LLM_BASE_URL` | Ollama local | Any OpenAI-compatible endpoint |
| `LLM_MODEL` | `qwen2.5:7b` | Model name |
| `VISION_MODEL` | _(disabled)_ | VLM for image → RAG description |
| `TUTOR_TTS_MODEL` | _(disabled)_ | TTS model for audio + karaoke |
| `TUTOR_VIDEO_ENABLED` | `false` | Generate slide video after explanations |
| `TUTOR_PROFILE_DB_PATH` | _(in-memory)_ | SQLite for student profiles |
| `TUTOR_LEDGER_DB_PATH` | _(disabled)_ | SQLite for RL + engagement + badges |

### Recommended model stacks

| Use case | LLM | Embedding | VLM | TTS |
|---|---|---|---|---|
| Local / free | Qwen2.5:7b (Ollama) | multilingual-e5-small | LLaVA (Ollama) | Kokoro (local) |
| Cloud / best | Gemini 2.0 Flash | multilingual-e5-large | Gemini 2.0 Flash | OpenAI tts-1 |
| Groq (fast) | qwen-qwen2.5-72b | multilingual-e5-small | — | — |

---

## Running tests

### Tuteur library (src/tuteur)

```bash
pytest tests/tuteur/ -v
```

### Agentic layer (backend/agentic)

```bash
cd backend/agentic
pytest -v
```

### MLOps app (tests/)

```bash
pytest tests/ -v
```

### Frontend

```bash
cd frontend
npm test
```

### All at once (CI-equivalent)

```bash
# Python
ruff check app orchestration tests backend/agentic/src
pytest tests/ tests/tuteur/ -q

# Frontend
cd frontend && npm ci && npm test && npm run build
```

---

## Cloud deployment

### Docker Compose (single server / VPS)

```bash
# Production .env
TUTOR_ENVIRONMENT=production
TUTOR_ALLOW_MOCKS=false
TUTOR_GENAI_BACKEND=http   # or tuteur if running LLM on the same server
# Set all service URLs, API keys, DB paths...

docker compose up -d
```

### GitHub Actions CI/CD (automated)

The workflow at `.github/workflows/ci.yml` runs on every PR to `main`:

1. **Ruff** — Python linting
2. **Pytest** — all Python tests
3. **Docker build** — builds and smoke-tests the API image
4. **Frontend build** — `npm ci && npm test && npm run build`

Add a `deploy` job to push to your cloud provider after CI passes
(see the `Cloud deployment` section in `docs/DEPLOYMENT.md`).

### Railway / Render (one-click PaaS)

Both platforms support Docker Compose deployment. Point them at this repo
with `compose.yaml` as the entry point.

Environment variables are set in the platform's dashboard —
copy from `.env.example` and fill in your production values.

### AWS / GCP / Azure (Kubernetes)

See `docs/DEPLOYMENT.md` for Helm chart and Kubernetes manifests.
The recommended architecture is:

```
Ingress (nginx/ALB)
  → frontend (static files served by nginx or Vercel)
  → api (FastAPI, 2+ replicas)
  → rl  (FastAPI, 1 replica)
  → mlflow (1 replica, persistent volume for SQLite)
  → airflow (scheduler + webserver)
  → postgres (Airflow metadata)
  → prometheus + grafana
```

---

## Feature map

| Feature | Status | Config |
|---|---|---|
| GenAI quiz/explanation/flashcards | ✅ | `TUTOR_GENAI_BACKEND=tuteur` |
| RAG (hybrid BM25 + dense) | ✅ | `LLM_*` + `EMBEDDING_MODEL` |
| VLM image → RAG chunks | ✅ | `VISION_MODEL` |
| LinUCB adaptive difficulty | ✅ | `TUTOR_RL_SERVICE_URL` |
| Student profile + onboarding | ✅ | `TUTOR_PROFILE_DB_PATH` |
| Multilingual (AR/FR/EN) | ✅ | `LLM_MODEL` (multilingual) |
| School-level prompt tone | ✅ | Automatic from profile |
| Audio + karaoke | ✅ | `TUTOR_TTS_MODEL` |
| Color vision adaptation | ✅ | Declared in profile |
| Engagement scores + badges | ✅ | `TUTOR_LEDGER_DB_PATH` |
| Parent/supervisor report + PDF | ✅ | `TUTOR_LEDGER_DB_PATH` |
| Video summary | ✅ | `TUTOR_VIDEO_ENABLED=true` |
| MLflow tracing | ✅ | `MLFLOW_TRACKING_URI` |
| Airflow orchestration | ✅ | `docker compose up` |
| Prometheus + Grafana monitoring | ✅ | `docker compose up` |
| Security guard model | 🔜 | `TUTOR_GUARD_MODEL` (placeholder) |

---

## Student history fixtures

Synthetic student interaction data lives in `data/fixtures/students/`.
It represents 5 students with varied profiles using the platform over
one week on the photosynthesis course.

| Student | Profile | Highlights |
|---|---|---|
| `student-demo-1` | Standard, FR, collège | Curious (high), 2 sessions, 33 attempts |
| `student-demo-2` | Dyslexie, FR, primaire | Persistent (high), audio+karaoke, improved with remediation |
| `student-demo-3` | Protanopie, AR, lycée | Arabic RTL, color adaptation, 85% success rate |
| `student-demo-4` | TDAH, EN, université | Autonomous (high), 25 attempts in 20 min, 6 badges |
| `student-demo-5` | Autisme+basse vision, FR | Full accessibility stack, text_scale 1.5, high contrast |

Use these fixtures to:
- **Demo** the platform without real user data
- **Warm-start** the LinUCB policy before real students arrive
- **Benchmark** recommendation quality offline

---

## Contributing

This project is developed on `integration/main`. Each feature lives in its
own section of the codebase; see the architecture diagram above.

```bash
# Run the full quality check before opening a PR
ruff check .
pytest -q
cd frontend && npm test
```

All commits must be attributed to the team member who wrote the code.
Never commit secrets, PII or real student data.
