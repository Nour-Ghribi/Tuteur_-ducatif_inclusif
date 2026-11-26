"""DEVELOPMENT HARNESS — not the team's application.

A minimal FastAPI app that mounts the tutor router so the frontend and the workflows can be run
locally (``python -m tutor_agentic.dev_server``). The team's real FastAPI application (MLOps
scaffold) should mount ``create_tutor_router`` itself and own /health, /ready and /metrics; this
file then becomes unnecessary. It refuses to run outside development/test.

With no ``TUTOR_DEV_AUTH_TOKENS`` configured it generates two throw-away tokens at startup and
prints them (a student and a teacher); they are never written to disk.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import create_tutor_router, install_error_handlers
from .auth import build_authenticator
from .config import DevIdentity, Settings, get_settings
from .service import TutorService

log = logging.getLogger("tutor_agentic.dev_server")
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def _with_dev_tokens(settings: Settings) -> tuple[Settings, dict[str, str]]:
    if settings.dev_auth_tokens:
        return settings, {}
    shown = {"student": secrets.token_urlsafe(24), "teacher": secrets.token_urlsafe(24)}
    tokens = {
        shown["student"]: DevIdentity(subject_ref="student-dev-1", role="student"),
        shown["teacher"]: DevIdentity(
            subject_ref="teacher-dev-1", role="teacher", class_ids=["class-demo-a"]
        ),
    }
    return settings.model_copy(update={"dev_auth_tokens": tokens}), shown


def create_dev_app(settings: Settings | None = None, tutor=None) -> FastAPI:
    settings = settings or get_settings()
    if not settings.is_development:
        raise RuntimeError(
            "the development harness only runs with TUTOR_ENVIRONMENT=development|test"
        )
    settings, shown = _with_dev_tokens(settings)
    service = TutorService.from_settings(settings, tutor=tutor)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        for role, token in shown.items():
            print(f"[dev] {role} token: {token}")
        yield
        await service.aclose()

    app = FastAPI(title="tutor-agentic (dev harness)", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(
        create_tutor_router(service, build_authenticator(settings)), prefix="/api/v1"
    )
    install_error_handlers(app)

    @app.get("/ready")
    async def ready() -> dict:
        return service.readiness()

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_dev_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
