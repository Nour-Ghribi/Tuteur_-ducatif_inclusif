"""RL recommendation microservice.

Exposes the LinUCB adaptive policy (or rule-based fallback) over HTTP so the
agentic layer can call it via TUTOR_RL_SERVICE_URL=http://rl:8001.

Endpoints
---------
POST /v1/recommend   RecommendationRequest  → RecommendationResponse
POST /v1/outcomes    OutcomeRequest         → OutcomeResponse
GET  /health                               → {"status": "ok", ...}
GET  /ready                                → {"status": "ok"|"degraded", ...}

Environment
-----------
RL_POLICY_CHECKPOINT   path to LinUCB .pkl checkpoint (optional)
RL_SERVICE_API_KEY     bearer token expected in Authorization header (optional)
RL_HOST                bind host (default 0.0.0.0)
RL_PORT                bind port (default 8001)
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .policy_bridge import recommend
from .schemas import (
    OutcomeRequest,
    OutcomeResponse,
    RecommendationRequest,
    RecommendationResponse,
)

# ---------------------------------------------------------------------------
# Policy loading (optional — falls back to rule-based if not configured)
# ---------------------------------------------------------------------------

_CHECKPOINT = os.getenv("RL_POLICY_CHECKPOINT", "")
_policy = None
_policy_error: str | None = None

if _CHECKPOINT:
    try:
        from tuteur.adaptive.policy import LinUCBPolicy
        _policy = LinUCBPolicy.load(Path(_CHECKPOINT))
    except Exception as exc:
        _policy_error = f"{type(exc).__name__}: {exc}"

# ---------------------------------------------------------------------------
# Auth (optional shared secret)
# ---------------------------------------------------------------------------

_API_KEY = os.getenv("RL_SERVICE_API_KEY", "")


def _check_auth(request: Request) -> None:
    if not _API_KEY:
        return
    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token.encode(), _API_KEY.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ---------------------------------------------------------------------------
# In-memory outcome store (phase-1: accepts outcomes, logs them)
# A persistent store (Redis / Postgres) replaces this in production.
# ---------------------------------------------------------------------------

_outcomes: list[dict] = []

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Tuteur RL Service",
    version="1.0.0",
    description="LinUCB adaptive recommendation service for the inclusive educational tutor.",
)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "service": "rl"}


@app.get("/ready", tags=["system"])
def ready() -> dict:
    mode = "linucb" if _policy is not None else "rule-based"
    return {
        "status": "ok",
        "policy_mode": mode,
        "checkpoint": _CHECKPOINT or None,
        "checkpoint_error": _policy_error,
    }


@app.post("/v1/recommend", response_model=RecommendationResponse, tags=["rl"])
async def post_recommend(body: RecommendationRequest, request: Request) -> RecommendationResponse:
    _check_auth(request)
    return recommend(
        features=body.features,
        available=body.available_activities,
        student_ref=body.student_ref,
        topic=body.topic,
        linucb_policy=_policy,
    )


@app.post("/v1/outcomes", response_model=OutcomeResponse, tags=["rl"])
async def post_outcome(body: OutcomeRequest, request: Request) -> OutcomeResponse:
    """Receives reward signals. Logged now; online LinUCB update in phase 2."""
    _check_auth(request)
    _outcomes.append(body.model_dump())
    # TODO phase 2: trigger online LinUCB weight update here
    return OutcomeResponse(accepted=True, simulated=False)


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.rl.main:app",
        host=os.getenv("RL_HOST", "0.0.0.0"),
        port=int(os.getenv("RL_PORT", "8001")),
        reload=False,
    )
