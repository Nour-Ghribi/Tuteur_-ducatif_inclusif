"""Configuration OpenTelemetry optionnelle pour l'API FastAPI."""

from __future__ import annotations

import os
from typing import Literal

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

ExporterName = Literal["console", "otlp"]


def _enabled(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"1", "true", "yes", "on"}


def configure_opentelemetry(app: FastAPI) -> TracerProvider | None:
    """Instrumente FastAPI quand OTEL_TRACES_ENABLED est activé."""
    if not _enabled(os.getenv("OTEL_TRACES_ENABLED")):
        return None

    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "tuteur-inclusif-api"),
            "service.version": app.version,
            "deployment.environment.name": os.getenv("APP_ENV", "development"),
            "data.classification": "synthetic-only",
        }
    )
    provider = TracerProvider(resource=resource)
    exporter_name: ExporterName = os.getenv("OTEL_TRACES_EXPORTER", "console").strip().lower()  # type: ignore[assignment]

    if exporter_name == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif exporter_name == "otlp":
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        if not endpoint:
            base_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
            endpoint = f"{base_endpoint.rstrip('/')}/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    else:
        raise ValueError("OTEL_TRACES_EXPORTER doit valoir 'console' ou 'otlp'.")

    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="health,metrics",
    )
    return provider
