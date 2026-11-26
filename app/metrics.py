"""Métriques Prometheus de l'API FastAPI."""

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.routing import Match

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Nombre total de requêtes HTTP reçues.",
    labelnames=("method", "endpoint", "status"),
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Durée des requêtes HTTP en secondes.",
    labelnames=("method", "endpoint"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


def _route_template(request: Request) -> str:
    """Retourne le chemin déclaré plutôt qu'une URL pouvant créer trop de labels."""
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match is Match.FULL:
            return getattr(route, "path", "unknown")
    return "unmatched"


async def observe_request(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Mesure le volume, le statut et la durée des requêtes applicatives."""
    endpoint = _route_template(request)
    started_at = time.perf_counter()
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        if endpoint != "/metrics":
            elapsed_seconds = time.perf_counter() - started_at
            HTTP_REQUESTS.labels(
                method=request.method,
                endpoint=endpoint,
                status=str(status_code),
            ).inc()
            HTTP_REQUEST_DURATION.labels(
                method=request.method,
                endpoint=endpoint,
            ).observe(elapsed_seconds)


def prometheus_metrics() -> Response:
    """Expose le registre Prometheus au format texte standard."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
