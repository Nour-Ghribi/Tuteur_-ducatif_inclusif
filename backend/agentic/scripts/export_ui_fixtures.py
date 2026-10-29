"""Exports real backend responses (mock services, simulated data) and the UI JSON Schema.

The frontend tests parse these files with the TypeScript (zod) schema and render every block, so a
change to ``schemas/ui.py`` that is not mirrored in ``frontend/src/ui-schema`` fails the frontend tests.

    python scripts/export_ui_fixtures.py ../../frontend/src/ui-schema/__fixtures__
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from tutor_agentic.auth import Principal
from tutor_agentic.config import Settings
from tutor_agentic.integrations.contracts import RetrievalResponse
from tutor_agentic.integrations.mocks import (
    FaultInjector,
    MockContentGenerationAdapter,
    MockRetrievalAdapter,
)
from tutor_agentic.schemas.common import AccessibilityPreferences, PresentationFormat
from tutor_agentic.schemas.requests import (
    AnswerSubmission,
    ExperienceRequest,
    RecommendationRequest,
    StudentAnswer,
    TeacherReportRequest,
)
from tutor_agentic.schemas.ui import UISpec
from tutor_agentic.service import TutorService
from tutor_agentic.telemetry import NoopSink, Telemetry

COURSE = "demo-bio-101"
TOPIC = "photosynthèse"
STUDENT = Principal(subject_ref="student-dev-1", role="student", auth_mode="dev_stub")
TEACHER = Principal(
    subject_ref="teacher-dev-1",
    role="teacher",
    class_ids=frozenset({"class-demo-a"}),
    auth_mode="dev_stub",
)


class ImageRetrieval(MockRetrievalAdapter):
    async def retrieve(self, request):
        response = await super().retrieve(request)
        for chunk in response.chunks[:1]:
            chunk.image_refs = ["img-demo-figure-1"]
        return RetrievalResponse(**response.model_dump())


def new_service() -> TutorService:
    return TutorService.from_settings(
        Settings(_env_file=None, environment="test"), Telemetry(NoopSink())
    )


async def build() -> dict[str, object]:
    out: dict[str, object] = {}
    service = new_service()

    def ask(message: str, fmt: PresentationFormat | None = None, **prefs) -> ExperienceRequest:
        return ExperienceRequest(
            message=message,
            course_id=COURSE,
            topic=TOPIC,
            requested_format=fmt,
            preferences=AccessibilityPreferences(**prefs),
        )

    for name, message in {
        "explanation": "Explique-moi ce chapitre simplement",
        "quiz": "Génère cinq questions",
        "flashcards": "Donne-moi des flashcards",
        "concept_map": "Fais une carte mentale",
        "steps": "Guide-moi étape par étape",
        "concept_cards": "Montre-moi les notions clés",
        "comparison": "Compare ces notions",
    }.items():
        out[name] = await service.create_experience(STUDENT, ask(message))

    quiz = out["quiz"]
    question_id = quiz.ui.blocks[0].questions[0].question_id
    out["remediation"] = await service.submit_answer(
        STUDENT,
        AnswerSubmission(question_id=question_id, answer=StudentAnswer(selected_option_id="b")),
    )
    out["recommendation"] = await service.recommend_next(
        STUDENT, RecommendationRequest(course_id=COURSE, topic=TOPIC)
    )
    out["progress"] = service.progress(STUDENT)
    out["teacher_report"] = await service.teacher_report(
        TEACHER,
        TeacherReportRequest(
            class_id="class-demo-a", period_start=date(2026, 9, 1), period_end=date(2026, 10, 1)
        ),
    )
    out["no_course_content"] = await service.create_experience(
        STUDENT, ExperienceRequest(message="Explain", course_id="unknown-course")
    )

    with_images = new_service()
    with_images._adapters.retrieval = ImageRetrieval(
        policy=with_images._adapters.retrieval._policy,
        telemetry=with_images._adapters.retrieval._telemetry,
    )
    out["explanation_with_image"] = await with_images.create_experience(STUDENT, ask("Explique"))

    broken = new_service()
    broken._adapters.generation = MockContentGenerationAdapter(
        faults=FaultInjector("unavailable"),
        policy=broken._adapters.generation._policy,
        telemetry=broken._adapters.generation._telemetry,
    )
    out["fallback"] = await broken.create_experience(STUDENT, ask("Explique"))
    return out


def main(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    responses = asyncio.run(build())
    for name, response in responses.items():
        (target / f"{name}.json").write_text(
            json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    (target / "ui-spec.schema.json").write_text(
        json.dumps(UISpec.model_json_schema(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(responses)} responses + schema written to {target}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixtures"))
