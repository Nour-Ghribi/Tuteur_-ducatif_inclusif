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
from .engagement import EngagementService
from .profiles import (
    InMemoryProfileStore,
    ProfileStore,
    SQLiteProfileStore,
    merge_with_request,
    needs_to_preferences,
    SCHOOL_LEVEL_DIFFICULTY,
)
from .profiles.models import StudentProfile
from .routing import IntentRouter
from .schemas.common import AccessibilityPreferences, Difficulty, Workflow
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
        profiles: ProfileStore | None = None,
        engagement: EngagementService | None = None,
    ) -> None:
        self._settings = settings
        self._adapters = adapters
        self._telemetry = telemetry
        self._store = store or InMemoryIssuedActivityStore(ttl_s=settings.issued_item_ttl_s)
        self._history = history or InMemoryStudentHistory()
        self._profiles: ProfileStore = profiles or InMemoryProfileStore()
        ledger_path = getattr(settings, "ledger_db_path", None)
        self._engagement = engagement or EngagementService(ledger_path)
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
        # Use SQLite profile store if a DB path is configured, else in-memory
        profile_db = getattr(settings, "profile_db_path", None)
        profiles: ProfileStore = (
            SQLiteProfileStore(profile_db) if profile_db else InMemoryProfileStore()
        )
        ledger_db = getattr(settings, "ledger_db_path", None)
        return cls(
            settings=settings,
            adapters=build_adapters(settings, telemetry, tutor=tutor),
            telemetry=telemetry,
            profiles=profiles,
            engagement=EngagementService(ledger_db),
        )

    @property
    def graph(self):
        return self._graph

    @property
    def profiles(self) -> ProfileStore:
        return self._profiles

    # --- profile helpers -----------------------------------------------------------------------

    def _load_profile(self, subject_ref: str | None) -> StudentProfile | None:
        if subject_ref is None:
            return None
        return self._profiles.get(subject_ref)

    def _merge_preferences(
        self, profile: StudentProfile | None, request_prefs: AccessibilityPreferences
    ) -> AccessibilityPreferences:
        """Merges server-side profile preferences with per-request client preferences.

        Client preferences can tighten (turn more things on) but cannot disable
        what a declared need requires (e.g. a dyslexic student's simplified_language
        stays True even if the client sends simplified_language=False).
        """
        if profile is None:
            return request_prefs
        merged_dict = merge_with_request(
            profile.rendering_preferences,
            request_prefs.model_dump(),
        )
        return AccessibilityPreferences(**merged_dict)

    def _profile_state_extras(self, profile: StudentProfile | None) -> dict:
        """Extracts profile fields that go into TutorState."""
        if profile is None:
            return {}
        return {
            "school_level": profile.school_level,
            "cognitive_need": profile.cognitive_need,
            "student_language": profile.language_preference,
        }

    def _baseline_difficulty(self, profile: StudentProfile | None) -> Difficulty | None:
        if profile is None:
            return None
        raw = SCHOOL_LEVEL_DIFFICULTY.get(profile.school_level, "medium")
        return Difficulty(raw)

    # --- use cases -----------------------------------------------------------------------------

    async def create_experience(
        self, principal: Principal, request: ExperienceRequest
    ) -> TutorResponse:
        principal.require_role("student", "teacher")
        student_ref = principal.subject_ref if principal.role == "student" else None
        profile = self._load_profile(student_ref)

        # Merge profile preferences with client's per-request preferences
        merged_prefs = self._merge_preferences(profile, request.preferences)
        request = request.model_copy(update={"preferences": merged_prefs})

        # Use profile language as fallback when the request carries no language
        if request.language is None and profile is not None:
            request = request.model_copy(
                update={"language": profile.language_preference}
            )

        state = await self._run(
            Workflow.EXPERIENCE,
            principal,
            experience=request,
            student_ref=student_ref,
            history=self._snapshot(student_ref, request.topic, None),
            **self._profile_state_extras(profile),
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

        profile = self._load_profile(principal.subject_ref)
        merged_prefs = self._merge_preferences(profile, submission.preferences)
        submission = submission.model_copy(update={"preferences": merged_prefs})

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
            **self._profile_state_extras(profile),
        )
        evaluation = state.get("evaluation")
        if evaluation is not None:
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
            # Run engagement + badge evaluation after each graded answer
            self._engagement.run_after_session(principal.subject_ref)
        self._persist(state, principal, issued.course_id)
        return self._response(state)

    async def recommend_next(
        self, principal: Principal, request: RecommendationRequest
    ) -> TutorResponse:
        principal.require_role("student")
        profile = self._load_profile(principal.subject_ref)
        merged_prefs = self._merge_preferences(profile, request.preferences)
        request = request.model_copy(update={"preferences": merged_prefs})

        state = await self._run(
            Workflow.LEARNING_PATH,
            principal,
            recommendation_request=request,
            student_ref=principal.subject_ref,
            history=self._snapshot(principal.subject_ref, request.topic, None),
            **self._profile_state_extras(profile),
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
        """The learner's own progress: history snapshot + engagement scores + badges."""
        principal.require_role("student")
        ref = principal.subject_ref
        snapshot = self._history.snapshot(ref, topic=None, competence=None)

        # Engagement scores (from ledger if available, else empty)
        eng_snapshot = self._engagement.latest_snapshot(ref)
        badges = self._engagement.earned_badges(ref)

        blocks = ui_planner.progress_blocks(snapshot, eng_snapshot, badges)
        spec = UISpec(blocks=blocks, meta=UIMeta())
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
