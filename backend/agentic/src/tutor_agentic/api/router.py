"""Mountable FastAPI router. This package deliberately does not create a FastAPI application:
the team's application (MLOps scaffold) mounts it::

    from tutor_agentic.api import create_tutor_router, install_error_handlers

    app.include_router(create_tutor_router(service, authenticator), prefix="/api/v1")
    install_error_handlers(app)
"""

# No ``from __future__ import annotations``: FastAPI must resolve the locally defined
# ``CurrentPrincipal`` dependency alias at definition time.
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Path, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..auth import Authenticator, Principal
from ..errors import TutorError
from ..schemas.common import Identifier
from ..schemas.requests import (
    ActivityOutcome,
    AnswerSubmission,
    ExperienceRequest,
    RecommendationRequest,
    TeacherReportRequest,
)
from ..schemas.responses import ErrorBody, ErrorResponse, OutcomeAck, TutorResponse
from ..service import TutorService

_ERRORS = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
    504: {"model": ErrorResponse},
}


def create_tutor_router(service: TutorService, authenticator: Authenticator) -> APIRouter:
    router = APIRouter()
    bearer = HTTPBearer(auto_error=False)

    def current_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Principal:
        return authenticator.authenticate(credentials.credentials if credentials else None)

    CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

    @router.post(
        "/tutor/experiences", response_model=TutorResponse, tags=["tutor"], responses=_ERRORS
    )
    async def create_experience(
        body: ExperienceRequest, principal: CurrentPrincipal
    ) -> TutorResponse:
        return await service.create_experience(principal, body)

    @router.post("/tutor/answers", response_model=TutorResponse, tags=["tutor"], responses=_ERRORS)
    async def submit_answer(body: AnswerSubmission, principal: CurrentPrincipal) -> TutorResponse:
        return await service.submit_answer(principal, body)

    @router.post(
        "/tutor/recommendations", response_model=TutorResponse, tags=["tutor"], responses=_ERRORS
    )
    async def recommend_next(
        body: RecommendationRequest, principal: CurrentPrincipal
    ) -> TutorResponse:
        return await service.recommend_next(principal, body)

    @router.post(
        "/tutor/recommendations/{recommendation_id}/outcome",
        response_model=OutcomeAck,
        tags=["tutor"],
        responses=_ERRORS,
    )
    async def record_outcome(
        recommendation_id: Annotated[Identifier, Path()],
        body: ActivityOutcome,
        principal: CurrentPrincipal,
    ) -> OutcomeAck:
        return await service.record_outcome(principal, recommendation_id, body)

    @router.post(
        "/teacher/reports", response_model=TutorResponse, tags=["teacher"], responses=_ERRORS
    )
    async def teacher_report(
        body: TeacherReportRequest, principal: CurrentPrincipal
    ) -> TutorResponse:
        return await service.teacher_report(principal, body)

    @router.get("/tutor/progress", response_model=TutorResponse, tags=["tutor"], responses=_ERRORS)
    async def progress(principal: CurrentPrincipal) -> TutorResponse:
        return service.progress(principal)

    @router.get(
        "/assets/{asset_id}", tags=["assets"], responses=_ERRORS, response_class=FileResponse
    )
    async def get_asset(
        asset_id: Annotated[Identifier, Path()], principal: CurrentPrincipal
    ) -> FileResponse:
        asset = service.asset(principal, asset_id)
        return FileResponse(
            asset.path,
            media_type=asset.content_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )

    return router


async def _tutor_error_handler(request: Request, exc: TutorError) -> JSONResponse:
    # Messages of 5xx errors stay generic; details go to logs/telemetry, not to clients.
    message = exc.message if exc.http_status < 500 else exc.public_message
    body = ErrorResponse(
        error=ErrorBody(
            code=exc.code, message=message, request_id=exc.request_id or uuid.uuid4().hex
        )
    )
    headers = {"WWW-Authenticate": "Bearer"} if exc.http_status == 401 else None
    return JSONResponse(body.model_dump(), status_code=exc.http_status, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    """Registers the handler for this package's errors only; other app handlers are untouched."""
    app.add_exception_handler(TutorError, _tutor_error_handler)
