"""Shared fixtures. Everything runs on mocks: no network, no models, no real learner data."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tutor_agentic.api import create_tutor_router, install_error_handlers
from tutor_agentic.auth import DevTokenAuthenticator, Principal
from tutor_agentic.config import DevIdentity, Settings
from tutor_agentic.integrations import AdapterSet
from tutor_agentic.integrations.base import ResiliencePolicy
from tutor_agentic.integrations.mocks import (
    MockAnswerEvaluationAdapter,
    MockContentGenerationAdapter,
    MockInclusionAdapter,
    MockLearningRecordsAdapter,
    MockRecommendationAdapter,
    MockRetrievalAdapter,
)
from tutor_agentic.service import TutorService
from tutor_agentic.telemetry import InMemorySink, Telemetry

STUDENT_TOKEN = "dev-student-token-0123456789abcdef"
OTHER_STUDENT_TOKEN = "dev-student2-token-0123456789abcdef"
TEACHER_TOKEN = "dev-teacher-token-0123456789abcdef"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        adapter_timeout_s=0.2,
        adapter_max_retries=2,
        adapter_backoff_s=0,
    )


@pytest.fixture
def sink() -> InMemorySink:
    return InMemorySink()


@pytest.fixture
def telemetry(sink: InMemorySink) -> Telemetry:
    return Telemetry(sink)


@pytest.fixture
def adapter_kwargs(settings: Settings, telemetry: Telemetry) -> dict[str, Any]:
    policy = ResiliencePolicy(
        timeout_s=settings.adapter_timeout_s,
        max_retries=settings.adapter_max_retries,
        backoff_s=settings.adapter_backoff_s,
    )
    return {"policy": policy, "telemetry": telemetry}


@pytest.fixture
def make_adapters(adapter_kwargs: dict[str, Any]) -> Callable[..., AdapterSet]:
    def factory(**overrides: Any) -> AdapterSet:
        kw = adapter_kwargs
        adapters = {
            "retrieval": MockRetrievalAdapter(**kw),
            "generation": MockContentGenerationAdapter(**kw),
            "evaluation": MockAnswerEvaluationAdapter(**kw),
            "recommendation": MockRecommendationAdapter(**kw),
            "learning_records": MockLearningRecordsAdapter(**kw),
            "inclusion": MockInclusionAdapter(**kw),
            "intent_classifier": None,
        }
        adapters.update(overrides)
        return AdapterSet(**adapters)

    return factory


@pytest.fixture
def make_service(
    settings: Settings, telemetry: Telemetry, make_adapters: Callable[..., AdapterSet]
) -> Callable[..., TutorService]:
    def factory(
        settings_override: Settings | None = None, **adapter_overrides: Any
    ) -> TutorService:
        return TutorService(
            settings=settings_override or settings,
            adapters=make_adapters(**adapter_overrides),
            telemetry=telemetry,
        )

    return factory


@pytest.fixture
def student() -> Principal:
    return Principal(subject_ref="student-dev-1", role="student", auth_mode="dev_stub")


@pytest.fixture
def teacher() -> Principal:
    return Principal(
        subject_ref="teacher-dev-1",
        role="teacher",
        class_ids=frozenset({"class-demo-a"}),
        auth_mode="dev_stub",
    )


@pytest.fixture
def authenticator() -> DevTokenAuthenticator:
    return DevTokenAuthenticator(
        {
            STUDENT_TOKEN: DevIdentity(subject_ref="student-dev-1", role="student"),
            OTHER_STUDENT_TOKEN: DevIdentity(subject_ref="student-dev-2", role="student"),
            TEACHER_TOKEN: DevIdentity(
                subject_ref="teacher-dev-1", role="teacher", class_ids=["class-demo-a"]
            ),
        },
        environment="test",
    )


@pytest.fixture
def make_client(make_service, authenticator) -> Callable[..., TestClient]:
    """Test-only FastAPI app mounting the router, as the team's application would."""

    def factory(**service_kwargs: Any) -> TestClient:
        app = FastAPI()
        app.include_router(
            create_tutor_router(make_service(**service_kwargs), authenticator), prefix="/api/v1"
        )
        install_error_handlers(app)
        return TestClient(app)

    return factory


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
