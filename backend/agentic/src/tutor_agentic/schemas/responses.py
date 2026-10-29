"""Outbound API models."""

from __future__ import annotations

from enum import StrEnum

from .common import Identifier, StrictModel, Workflow
from .ui import UISpec


class ResponseStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"  # usable answer, but a dependency was skipped or failed
    FAILED = "failed"  # only a safe fallback could be produced


class TutorResponse(StrictModel):
    request_id: str
    workflow: Workflow
    intent: str | None = None
    status: ResponseStatus
    ui: UISpec


class OutcomeAck(StrictModel):
    recommendation_id: Identifier
    accepted: bool
    simulated: bool


class ErrorBody(StrictModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(StrictModel):
    error: ErrorBody
