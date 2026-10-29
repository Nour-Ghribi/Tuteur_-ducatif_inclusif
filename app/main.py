"""Point d'entrée FastAPI du tuteur éducatif inclusif."""

import os

from fastapi import FastAPI, Response

from app.artifact_registry import get_validated_artifacts
from app.metrics import observe_request, prometheus_metrics
from app.mock_services import choose_mock_activity, correct_mock_answer, generate_mock_quiz
from app.schemas import (
    HealthResponse,
    NextActivityRequest,
    NextActivityResponse,
    QuizRequest,
    QuizResponse,
    StudentAnswerRequest,
    StudentAnswerResponse,
)
from app.telemetry import configure_opentelemetry

APP_NAME = os.getenv("APP_NAME", "Tuteur éducatif inclusif API")
APP_ENV = os.getenv("APP_ENV", "development")

app = FastAPI(
    title=APP_NAME,
    version="0.1.0",
    description="API locale utilisant uniquement des services IA simulés.",
)

app.middleware("http")(observe_request)
configure_opentelemetry(app)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=APP_NAME,
        environment=APP_ENV,
        mode="simulation",
    )


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return prometheus_metrics()


@app.get("/artifacts/validated", tags=["mlops"])
def validated_artifacts() -> dict:
    """Expose les derniers artefacts batch sans déclencher Airflow."""
    return get_validated_artifacts()


@app.post("/generate-quiz", response_model=QuizResponse, tags=["education"])
def generate_quiz(request: QuizRequest) -> QuizResponse:
    return generate_mock_quiz(request)


@app.post("/student-answer", response_model=StudentAnswerResponse, tags=["education"])
def student_answer(request: StudentAnswerRequest) -> StudentAnswerResponse:
    return correct_mock_answer(request)


@app.post("/next-activity", response_model=NextActivityResponse, tags=["adaptation"])
def next_activity(request: NextActivityRequest) -> NextActivityResponse:
    return choose_mock_activity(request)

