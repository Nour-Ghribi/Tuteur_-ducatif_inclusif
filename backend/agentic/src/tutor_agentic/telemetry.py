"""Instrumentation hooks.

This module only *emits* events. Where they go (structured logs, MLflow tracing, Prometheus
metrics) is decided by the sink the MLOps setup plugs in; no observability backend is started
here. Events carry technical metadata only — never student messages or answers.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Protocol

AttrValue = str | int | float | bool | None

request_id_var: ContextVar[str | None] = ContextVar("tutor_request_id", default=None)

ADAPTER_CALL = "tutor.adapter.call"
WORKFLOW_COMPLETED = "tutor.workflow.completed"
VERIFICATION_RESULT = "tutor.verification.result"

logger = logging.getLogger("tutor_agentic.telemetry")


@dataclass(frozen=True)
class TelemetryEvent:
    name: str
    attributes: Mapping[str, AttrValue]
    request_id: str | None = None


class TelemetrySink(Protocol):
    def emit(self, event: TelemetryEvent) -> None: ...


class NoopSink:
    def emit(self, event: TelemetryEvent) -> None:
        return None


class LoggingSink:
    """One JSON line per event; easy to ship with the team's log collector."""

    def emit(self, event: TelemetryEvent) -> None:
        payload = {"event": event.name, "request_id": event.request_id, **event.attributes}
        logger.info(json.dumps(payload, default=str))


@dataclass
class InMemorySink:
    """Collects events; used by tests and local debugging."""

    events: list[TelemetryEvent] = field(default_factory=list)

    def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)

    def named(self, name: str) -> list[TelemetryEvent]:
        return [e for e in self.events if e.name == name]


class Telemetry:
    """Safe facade: a failing sink must never break a student request."""

    def __init__(self, sink: TelemetrySink | None = None) -> None:
        self._sink = sink or LoggingSink()

    def emit(self, name: str, **attributes: AttrValue) -> None:
        event = TelemetryEvent(name=name, attributes=attributes, request_id=request_id_var.get())
        try:
            self._sink.emit(event)
        except Exception:  # pragma: no cover - defensive
            logger.debug("telemetry sink failed", exc_info=True)

    def adapter_call(
        self,
        *,
        service: str,
        operation: str,
        outcome: str,
        latency_ms: float,
        attempts: int,
        error_code: str | None = None,
    ) -> None:
        self.emit(
            ADAPTER_CALL,
            service=service,
            operation=operation,
            outcome=outcome,
            latency_ms=round(latency_ms, 2),
            attempts=attempts,
            error_code=error_code,
        )
