"""FastAPI application — Tuteur éducatif inclusif.

Mounts the agentic tutor router (LangGraph orchestration) produced by the
agentic-orchestration-ui team onto this MLOps scaffold, which owns:
  - /health, /ready, /metrics  (infrastructure)
  - /artifacts/validated       (MLOps batch registry)
  - /api/v1/...                (delegated entirely to tutor_agentic)

Environment variables (all prefixed TUTOR_):
  TUTOR_GENAI_BACKEND   mock | tuteur | http   (default: mock)
  TUTOR_ENVIRONMENT     development | staging | production
  TUTOR_*               see backend/agentic/src/tutor_agentic/config.py for full list
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.artifact_registry import get_validated_artifacts
from app.metrics import observe_request, prometheus_metrics
from app.telemetry import configure_opentelemetry

# ---------------------------------------------------------------------------
# Agentic layer wiring
# ---------------------------------------------------------------------------
from tutor_agentic.api import create_tutor_router, install_error_handlers
from tutor_agentic.auth import build_authenticator
from tutor_agentic.config import get_settings
from tutor_agentic.schemas.responses import ResponseStatus
from tutor_agentic.service import TutorService

APP_NAME = os.getenv("APP_NAME", "Tuteur éducatif inclusif")
APP_ENV = os.getenv("APP_ENV", os.getenv("TUTOR_ENVIRONMENT", "development"))

# ---------------------------------------------------------------------------
# CORS origins — tighten in production via env
# ---------------------------------------------------------------------------
_CORS_ORIGINS = [o.strip() for o in os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
).split(",") if o.strip()]

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    settings = get_settings()

    # TutorService is created once and shared across all requests.
    service = TutorService.from_settings(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await service.aclose()

    app = FastAPI(
        title=APP_NAME,
        version="1.0.0",
        description=(
            "Tuteur éducatif inclusif — GenAI + RAG + RL + MLOps. "
            "Education endpoints live under /api/v1/tutor and /api/v1/teacher."
        ),
        lifespan=lifespan,
    )

    # --- middleware -----------------------------------------------------------
    app.middleware("http")(observe_request)
    configure_opentelemetry(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
        allow_credentials=False,
    )

    # --- infrastructure endpoints --------------------------------------------
    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "service": APP_NAME, "environment": APP_ENV}

    @app.get("/ready", tags=["system"])
    def ready() -> dict:
        """Reports which adapters are real, mocked or unconfigured."""
        info = service.readiness()
        degraded = any(m == "mock" for m in info.get("adapters", {}).values())
        return {**info, "status": "degraded" if degraded else "ok"}

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return prometheus_metrics()

    @app.get("/artifacts/validated", tags=["mlops"])
    def validated_artifacts() -> dict:
        """Exposes the latest batch-validated artefacts without triggering Airflow."""
        return get_validated_artifacts()

    # --- agentic tutor router -------------------------------------------------
    # All education and recommendation logic lives here; this file owns nothing
    # about how sessions, graphs or prompts work.
    authenticator = build_authenticator(settings)
    app.include_router(
        create_tutor_router(service, authenticator),
        prefix="/api/v1",
    )
    install_error_handlers(app)

    return app


# Module-level instance consumed by uvicorn / Docker CMD.
app = create_app()
