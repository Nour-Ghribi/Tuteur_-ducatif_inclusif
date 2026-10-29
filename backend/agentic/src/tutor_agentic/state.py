"""Typed LangGraph state.

The state only holds what the workflow needs. Learner identity is a pseudonymous ``student_ref``;
no names, emails or raw history are ever placed here.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

from .history import HistorySnapshot
from .integrations.contracts import (
    LearningSummariesResponse,
    RemediationInput,
    RetrievedChunk,
)
from .routing.intents import IntentDecision
from .schemas.common import ActivityType, Difficulty, Workflow
from .schemas.content import EducationalContent, GenerationTask, QuizItem
from .schemas.requests import (
    AnswerSubmission,
    ExperienceRequest,
    RecommendationRequest,
    TeacherReportRequest,
)
from .schemas.responses import ResponseStatus
from .schemas.ui import UIBlock, UISpec, VerificationReport


class NodeError(BaseModel):
    node: str
    code: str
    service: str | None = None
    fatal: bool = False


class WorkflowPlan(BaseModel):
    task: GenerationTask | None  # None: no content generation needed
    topic: str
    retrieval_query: str
    needs_retrieval: bool = True
    needs_recommendation: bool = False
    n_items: int | None = Field(None, ge=1, le=20)
    difficulty: Difficulty | None = None


class IssuedQuestion(BaseModel):
    """A question served to a learner, kept server-side with its answer key."""

    item: QuizItem
    owner_ref: str
    course_id: str
    topic: str


class GenerationOutcome(BaseModel):
    content: EducationalContent
    prompt_version: str | None = None
    model_id: str | None = None
    pages_used: list[int] = Field(default_factory=list)
    invalid_citations: list[int] = Field(default_factory=list)


class AnswerEvaluation(BaseModel):
    question_id: str
    is_correct: bool
    score: float = Field(ge=0, le=1)
    observed_errors: list[str] = Field(default_factory=list)
    method: Literal["answer_key", "genai_evaluator"]


class RecommendationOutcome(BaseModel):
    recommendation_id: str
    activity_type: ActivityType
    difficulty: Difficulty
    topic: str
    rationale: str | None = None
    policy_version: str | None = None


class TutorState(TypedDict, total=False):
    # --- inputs (set by the application layer) ---
    request_id: str
    workflow: Workflow
    actor_role: Literal["student", "teacher"]
    student_ref: str | None
    experience: ExperienceRequest
    answer_submission: AnswerSubmission
    issued_question: IssuedQuestion
    recommendation_request: RecommendationRequest
    report_request: TeacherReportRequest

    # --- server-side learner context (never supplied by the client) ---
    history: HistorySnapshot
    evidence_count: int  # wrong answers on this competence, including the current one
    remediation_input: RemediationInput

    # --- decisions and intermediate results ---
    intent: IntentDecision
    plan: WorkflowPlan
    context: list[RetrievedChunk]
    retrieval_status: Literal["ok", "empty", "unavailable", "skipped"]
    generation: GenerationOutcome | None
    generation_attempts: int
    verification: VerificationReport
    evaluation: AnswerEvaluation
    recommendation: RecommendationOutcome | None
    report_data: LearningSummariesResponse

    # --- output ---
    image_blocks: list[UIBlock]
    ui_blocks: list[UIBlock]
    fallback_used: bool
    ui: UISpec
    status: ResponseStatus
    issued_questions: list[QuizItem]  # persisted by the application layer after the run

    # --- accumulated diagnostics (reducers append across nodes) ---
    warnings: Annotated[list[str], operator.add]
    errors: Annotated[list[NodeError], operator.add]
    simulated_services: Annotated[list[str], operator.add]


def has_fatal_error(state: TutorState) -> bool:
    return any(e.fatal for e in state.get("errors", []))
