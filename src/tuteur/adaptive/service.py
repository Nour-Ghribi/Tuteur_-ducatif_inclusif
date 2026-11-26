"""Application service for the persisted adaptive tutoring workflow."""

from __future__ import annotations

from dataclasses import dataclass

from tuteur.adaptive.database import SQLiteRepository
from tuteur.adaptive.models import (
    AdaptiveRemediation,
    RemediationDecision,
    StudentState,
)
from tuteur.adaptive.policy import RemediationPolicy, RuleBasedPolicy
from tuteur.adaptive.state import StudentStateBuilder
from tuteur.generation import Tutor
from tuteur.schemas import QuizItem


@dataclass(frozen=True)
class FailureFlow:
    state: StudentState
    decision: RemediationDecision
    recommendation_id: str
    remediation: AdaptiveRemediation
    followup_question_id: str
    recovery_id: str
    used_fallback: bool
    fallback_error: str | None


class AdaptiveTutorService:
    """Orchestrate actual app services; mock mode only replaces external dependencies."""

    def __init__(
        self,
        repository: SQLiteRepository,
        tutor: Tutor,
        primary_policy: RemediationPolicy | None,
        fallback_policy: RemediationPolicy | None = None,
        primary_policy_error: str | None = None,
    ):
        self.repository = repository
        self.tutor = tutor
        self.primary_policy = primary_policy
        self.fallback_policy = fallback_policy or RuleBasedPolicy()
        self.primary_policy_error = primary_policy_error
        self.state_builder = StudentStateBuilder(repository)

    def start_session(
        self,
        *,
        student_id: str,
        course_id: str,
        title: str,
        source: str,
        reading_level: str = "standard",
        session_id: str | None = None,
    ) -> str:
        return self.repository.create_session(
            student_id, course_id, title, source, reading_level, session_id
        )

    def generate_quiz_question(
        self,
        *,
        session_id: str,
        course_id: str,
        topic: str,
        reading_level: str = "standard",
        question_id: str | None = None,
    ) -> tuple[str, QuizItem]:
        quiz = self.tutor.quiz(
            topic=topic,
            n=1,
            difficulty="moyen",
            types=("qcm", "vrai_faux"),
            reading_level=reading_level,
        )
        if not quiz.items:
            raise ValueError("The LLM returned an empty quiz")
        item = quiz.items[0]
        if item.type not in {"qcm", "vrai_faux"}:
            raise ValueError("The MVP requires a deterministically gradable quiz question")
        saved_id, _ = self.repository.save_question(
            session_id,
            course_id,
            item,
            prompt_tag="quiz-adaptive-v1",
            model_version=str(self.tutor.llm.model),
            question_id=question_id,
        )
        return saved_id, item

    def handle_failure(
        self,
        *,
        session_id: str,
        course_id: str,
        failed_attempt_id: str,
        failed_question_id: str,
        question: QuizItem,
        student_answer: str,
        reading_level: str = "standard",
        recommendation_id: str | None = None,
        followup_question_id: str | None = None,
    ) -> FailureFlow:
        state = self.state_builder.build(failed_attempt_id)
        decision, used_fallback, fallback_error = self._decide(state)
        rec_id = self.repository.create_recommendation(
            session_id, failed_attempt_id, state, decision, recommendation_id
        )
        remediation = self.tutor.adaptive_remediate(
            strategy_id=decision.strategy_id,
            question=question.question,
            student_answer=student_answer,
            correct_answer=question.answer,
            competence=question.competence,
            reading_level=reading_level,
        )
        self.repository.log_remediation_event(
            rec_id,
            "generated",
            decision.strategy_id,
            remediation.model_dump(mode="json"),
        )
        followup_id, _ = self.repository.save_question(
            session_id,
            course_id,
            remediation.retry_question,
            prompt_tag=f"{decision.strategy_id}-v1",
            model_version=str(self.tutor.llm.model),
            parent_question_id=failed_question_id,
            question_id=followup_question_id,
        )
        recovery_id = self.repository.create_pending_recovery(rec_id)
        return FailureFlow(
            state,
            decision,
            rec_id,
            remediation,
            followup_id,
            recovery_id,
            used_fallback,
            fallback_error,
        )

    def mark_remediation_event(self, flow: FailureFlow, event_type: str) -> str:
        if event_type not in {"displayed", "viewed", "completed"}:
            raise ValueError(f"Unsupported delivery event: {event_type}")
        return self.repository.log_remediation_event(
            flow.recommendation_id, event_type, flow.decision.strategy_id
        )

    def observe_followup(self, recommendation_id: str, attempt_id: str) -> bool:
        return self.repository.observe_recovery(recommendation_id, attempt_id)

    def _decide(self, state: StudentState) -> tuple[RemediationDecision, bool, str | None]:
        if self.primary_policy is not None:
            try:
                return self.primary_policy.recommend(state), False, None
            except Exception as exc:  # noqa: BLE001 - policy plugins fail safely and visibly
                error = f"LinUCB inference failed: {type(exc).__name__}: {exc}"
        else:
            error = self.primary_policy_error or "LinUCB checkpoint is unavailable"
        fallback = self.fallback_policy.recommend(state)
        fallback.reason = f"{fallback.reason} Fallback cause: {error}"
        return fallback, True, error
