"""Application layer: authorization, input resolution, graph invocation, persistence of issued
activities and learner history, and workflow telemetry. HTTP routes stay thin and call only this class.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from .assets import Asset
from .auth import Principal
from .config import Settings, get_settings
from .errors import NotFound, TutorError, WorkflowTimeout
from .graph import GraphDependencies, build_tutor_graph, ui_planner
from .history import Attempt, InMemoryStudentHistory, StudentHistoryStore
from .integrations import AdapterSet, build_adapters
from .integrations.contracts import OutcomeReport
from .routing import IntentRouter
from .schemas.common import Workflow
from .schemas.requests import (
    ActivityOutcome,
    AnswerSubmission,
    ExperienceRequest,
    RecommendationRequest,
    TeacherReportRequest,
)
from .schemas.responses import OutcomeAck, ResponseStatus, TutorResponse
from .schemas.ui import UIMeta, UISpec
from .state import IssuedQuestion, TutorState
from .store import InMemoryIssuedActivityStore, IssuedActivityStore
from .telemetry import WORKFLOW_COMPLETED, Telemetry, request_id_var


class TutorService:
    def __init__(
        self,
        *,
        settings: Settings,
        adapters: AdapterSet,
        telemetry: Telemetry,
        store: IssuedActivityStore | None = None,
        history: StudentHistoryStore | None = None,
    ) -> None:
        self._settings = settings
        self._adapters = adapters
        self._telemetry = telemetry
        self._store = store or InMemoryIssuedActivityStore(ttl_s=settings.issued_item_ttl_s)
        self._history = history or InMemoryStudentHistory()
        router = IntentRouter(adapters.intent_classifier, settings.intent_classifier_min_confidence)
        self._graph = build_tutor_graph(
            GraphDependencies(
                adapters=adapters, intent_router=router, settings=settings, telemetry=telemetry
            )
        )

    @classmethod
    def from_settings(
        cls, settings: Settings | None = None, telemetry: Telemetry | None = None, tutor: Any = None
    ) -> TutorService:
        settings = settings or get_settings()
        telemetry = telemetry or Telemetry()
        return cls(
            settings=settings,
            adapters=build_adapters(settings, telemetry, tutor=tutor),
            telemetry=telemetry,
        )

    @property
    def graph(self):
        return self._graph

    # --- use cases -----------------------------------------------------------------------------

    async def create_experience(
        self, principal: Principal, request: ExperienceRequest
    ) -> TutorResponse:
        principal.require_role("student", "teacher")
        student_ref = principal.subject_ref if principal.role == "student" else None
        state = await self._run(
            Workflow.EXPERIENCE,
            principal,
            experience=request,
            student_ref=student_ref,
            history=self._snapshot(student_ref, request.topic, None),
        )
        self._persist(state, principal, request.course_id)
        return self._response(state)

    async def submit_answer(
        self, principal: Principal, submission: AnswerSubmission
    ) -> TutorResponse:
        principal.require_role("student")
        issued = self._store.get_question(submission.question_id, principal.subject_ref)
        if issued is None:
            raise NotFound("Unknown or expired question.")
        competence = issued.item.skill
        prior_wrong = self._history.wrong_on_competence(principal.subject_ref, competence)
        state = await self._run(
            Workflow.ANSWER,
            principal,
            answer_submission=submission,
            issued_question=issued,
            student_ref=principal.subject_ref,
            history=self._snapshot(principal.subject_ref, issued.topic, competence),
            evidence_count=prior_wrong + 1,
        )
        evaluation = state.get("evaluation")
        if evaluation is not None:  # only graded answers enter the history and consume the question
            self._store.discard_question(submission.question_id, principal.subject_ref)
            self._history.record(
                principal.subject_ref,
                Attempt(
                    topic=issued.topic,
                    competence=competence,
                    correct=evaluation.is_correct,
                    score=evaluation.score,
                    time_spent_s=submission.time_spent_s,
                    observed_errors=evaluation.observed_errors,
                ),
            )
        self._persist(state, principal, issued.course_id)
        return self._response(state)

    async def recommend_next(
        self, principal: Principal, request: RecommendationRequest
    ) -> TutorResponse:
        principal.require_role("student")
        state = await self._run(
            Workflow.LEARNING_PATH,
            principal,
            recommendation_request=request,
            student_ref=principal.subject_ref,
            history=self._snapshot(principal.subject_ref, request.topic, None),
        )
        self._persist(state, principal, request.course_id)
        return self._response(state)

    async def record_outcome(
        self, principal: Principal, recommendation_id: str, outcome: ActivityOutcome
    ) -> OutcomeAck:
        """Forwards the activity outcome to the RL service (reward signal); no training here."""
        principal.require_role("student")
        if self._store.get_recommendation(recommendation_id, principal.subject_ref) is None:
            raise NotFound("Unknown or expired recommendation.")
        ack = await self._adapters.recommendation.report_outcome(
            OutcomeReport(
                recommendation_id=recommendation_id,
                student_ref=principal.subject_ref,
                completed=outcome.completed,
                score=outcome.score,
                time_spent_s=outcome.time_spent_s,
            )
        )
        return OutcomeAck(
            recommendation_id=recommendation_id, accepted=ack.accepted, simulated=ack.simulated
        )

    async def teacher_report(
        self, principal: Principal, request: TeacherReportRequest
    ) -> TutorResponse:
        principal.require_role("teacher")
        principal.require_class(request.class_id)
        state = await self._run(Workflow.TEACHER_REPORT, principal, report_request=request)
        return self._response(state)

    def progress(self, principal: Principal) -> TutorResponse:
        """The learner's own progress, from server-side history. No model call."""
        principal.require_role("student")
        snapshot = self._history.snapshot(principal.subject_ref, topic=None, competence=None)
        spec = UISpec(blocks=ui_planner.progress_blocks(snapshot), meta=UIMeta())
        return TutorResponse(
            request_id=uuid.uuid4().hex,
            workflow=Workflow.PROGRESS,
            intent=Workflow.PROGRESS.value,
            status=ResponseStatus.OK,
            ui=spec,
        )

    def asset(self, principal: Principal, asset_id: str) -> Asset:
        if self._adapters.assets is None or (asset := self._adapters.assets.get(asset_id)) is None:
            raise NotFound("Unknown asset.")
        return asset

    def readiness(self) -> dict[str, Any]:
        """For the team's /ready endpoint: reports which adapters are real, mocked or missing."""
        modes = self._adapters.modes()
        return {
            "environment": self._settings.environment,
            "adapters": modes,
            "using_mocks": any(m == "mock" for m in modes.values()),
        }

    async def aclose(self) -> None:
        await self._adapters.aclose()

    # --- internals -----------------------------------------------------------------------------

    def _snapshot(self, student_ref: str | None, topic: str | None, competence: str | None):
        if student_ref is None:
            return None
        return self._history.snapshot(student_ref, topic=topic, competence=competence)

    async def _run(self, workflow: Workflow, principal: Principal, **inputs: Any) -> TutorState:
        request_id = uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        initial: TutorState = {
            "request_id": request_id,
            "workflow": workflow,
            "actor_role": principal.role,
            "warnings": [],
            "errors": [],
            "simulated_services": [],
            **{k: v for k, v in inputs.items() if v is not None},
        }
        try:
            async with asyncio.timeout(self._settings.graph_timeout_s):
                state: TutorState = await self._graph.ainvoke(initial)
        except TimeoutError as exc:
            self._emit_completed(workflow, "timeout", started, None)
            raise WorkflowTimeout(request_id=request_id) from exc
        except TutorError as exc:
            exc.request_id = request_id
            self._emit_completed(workflow, "error", started, None)
            raise
        finally:
            request_id_var.reset(token)
        self._emit_completed(workflow, state["status"].value, started, state)
        return state

    def _emit_completed(
        self, workflow: Workflow, outcome: str, started: float, state: TutorState | None
    ) -> None:
        state = state or {}
        intent = state.get("intent")
        verification = state.get("verification")
        self._telemetry.emit(
            WORKFLOW_COMPLETED,
            workflow=workflow.value,
            outcome=outcome,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            intent=intent.intent.value if intent else None,
            intent_source=intent.source if intent else None,
            generation_attempts=state.get("generation_attempts"),
            verification_passed=verification.passed if verification else None,
            error_codes=",".join(sorted({e.code for e in state.get("errors", [])})) or None,
            simulated=bool(state.get("simulated_services")),
        )

    def _persist(self, state: TutorState, principal: Principal, course_id: str) -> None:
        if principal.role != "student":
            return
        topic = state["plan"].topic if state.get("plan") else ""
        for item in state.get("issued_questions", []):
            self._store.put_question(
                IssuedQuestion(
                    item=item, owner_ref=principal.subject_ref, course_id=course_id, topic=topic
                )
            )
        if (rec := state.get("recommendation")) is not None:
            self._store.put_recommendation(principal.subject_ref, rec)

    @staticmethod
    def _response(state: TutorState) -> TutorResponse:
        intent = state.get("intent")
        return TutorResponse(
            request_id=state["request_id"],
            workflow=state["workflow"],
            intent=intent.intent.value if intent else state["workflow"].value,
            status=state["status"],
            ui=state["ui"],
        )
