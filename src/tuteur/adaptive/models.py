from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, Field, model_validator

from tuteur.schemas import QuizItem

STATE_SCHEMA_VERSION = "student-state-v1"
VECTOR_SCHEMA_VERSION = "student-state-vector-19d-v1"

ACTION_IDS = (
    "A0_guided_hint",
    "A1_simplified_explanation",
    "A2_worked_example",
    "A3_scaffolded_mcq",
    "A4_targeted_revision",
)
StrategyId = Literal[
    "A0_guided_hint",
    "A1_simplified_explanation",
    "A2_worked_example",
    "A3_scaffolded_mcq",
    "A4_targeted_revision",
]

FEATURE_NAMES_19D = (
    "prior_answer_count",
    "recent_accuracy_5_including_current",
    "skill_attempt_count_prior",
    "skill_accuracy_prior",
    "consecutive_failures_including_current",
    "recent_performance_trend_3v3",
    "current_response_time_s",
    "time_since_previous_answer_s",
    "authored_question_difficulty",
    "prior_displayed_remediation_count",
    "prior_displayed_skill_remediation_count",
    "prior_observed_recovery_rate",
    "student_cold_start",
    "skill_cold_start",
    "recent_performance_trend_3v3__missing",
    "current_response_time_s__missing",
    "time_since_previous_answer_s__missing",
    "authored_question_difficulty__missing",
    "prior_observed_recovery_rate__missing",
)


class StudentState(BaseModel):
    schema_version: Literal["student-state-v1"] = STATE_SCHEMA_VERSION
    vector_schema_version: Literal["student-state-vector-19d-v1"] = VECTOR_SCHEMA_VERSION
    student_id: str
    skill_id: str
    current_attempt_id: str
    decision_time: datetime
    prior_answer_count: int = Field(ge=0)
    recent_accuracy_5_including_current: float = Field(ge=0, le=1)
    skill_attempt_count_prior: int = Field(ge=0)
    skill_accuracy_prior: float | None = Field(default=None, ge=0, le=1)
    consecutive_failures_including_current: int = Field(ge=1)
    recent_performance_trend_3v3: float | None = Field(default=None, ge=-1, le=1)
    current_response_time_s: float | None = Field(default=None, ge=0)
    time_since_previous_answer_s: float | None = Field(default=None, ge=0)
    authored_question_difficulty: float | None = Field(default=None, ge=0, le=1)
    prior_displayed_remediation_count: int = Field(ge=0)
    prior_displayed_skill_remediation_count: int = Field(ge=0)
    prior_observed_recovery_rate: float | None = Field(default=None, ge=0, le=1)
    student_cold_start: bool
    skill_cold_start: bool

    @model_validator(mode="after")
    def validate_cold_start(self):
        if self.student_cold_start != (self.prior_answer_count == 0):
            raise ValueError("student_cold_start must match prior_answer_count")
        if self.skill_cold_start != (self.skill_attempt_count_prior == 0):
            raise ValueError("skill_cold_start must match skill_attempt_count_prior")
        if self.skill_cold_start and self.skill_accuracy_prior is not None:
            raise ValueError("skill_accuracy_prior must be missing on skill cold start")
        if not self.skill_cold_start and self.skill_accuracy_prior is None:
            raise ValueError("skill_accuracy_prior is required when skill history exists")
        return self

    def to_vector(self) -> np.ndarray:
        nullable = (
            self.recent_performance_trend_3v3,
            self.current_response_time_s,
            self.time_since_previous_answer_s,
            self.authored_question_difficulty,
            self.prior_observed_recovery_rate,
        )
        values = np.asarray(
            [
                self.prior_answer_count,
                self.recent_accuracy_5_including_current,
                self.skill_attempt_count_prior,
                self.skill_accuracy_prior if self.skill_accuracy_prior is not None else 0.0,
                self.consecutive_failures_including_current,
                self.recent_performance_trend_3v3 or 0.0,
                self.current_response_time_s or 0.0,
                self.time_since_previous_answer_s or 0.0,
                self.authored_question_difficulty or 0.0,
                self.prior_displayed_remediation_count,
                self.prior_displayed_skill_remediation_count,
                self.prior_observed_recovery_rate or 0.0,
                float(self.student_cold_start),
                float(self.skill_cold_start),
                *(float(value is None) for value in nullable),
            ],
            dtype=np.float64,
        )
        if values.shape != (19,) or not np.isfinite(values).all():
            raise ValueError("Student-state encoding must contain 19 finite values")
        return values

    def snapshot_hash(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class RemediationDecision(BaseModel):
    strategy_id: StrategyId
    strategy_name: str
    policy_type: str
    policy_version: str
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    state_schema_version: str = STATE_SCHEMA_VERSION
    vector_schema_version: str = VECTOR_SCHEMA_VERSION
    state_hash: str
    input_valid: bool
    provenance: Literal["simulation_trained", "rule_based_fallback"]
    reason: str
    assignment_mechanism: str
    action_probability: float | None = Field(default=None, ge=0, le=1)


class _AdaptiveBase(BaseModel):
    diagnostic: str = Field(min_length=3)
    competence: str = Field(min_length=1)
    source_pages: list[int] = Field(min_length=1)
    retry_question: QuizItem


class GuidedHint(_AdaptiveBase):
    strategy_id: Literal["A0_guided_hint"] = "A0_guided_hint"
    hint: str = Field(min_length=3, max_length=400)
    guiding_question: str = Field(min_length=3)


class SimplifiedExplanation(_AdaptiveBase):
    strategy_id: Literal["A1_simplified_explanation"] = "A1_simplified_explanation"
    explanation: str = Field(min_length=3, max_length=1200)
    key_points: list[str] = Field(min_length=1, max_length=4)


class WorkedExample(_AdaptiveBase):
    strategy_id: Literal["A2_worked_example"] = "A2_worked_example"
    example_problem: str = Field(min_length=3)
    steps: list[str] = Field(min_length=2, max_length=8)
    conclusion: str = Field(min_length=3)


class ScaffoldedMCQ(_AdaptiveBase):
    strategy_id: Literal["A3_scaffolded_mcq"] = "A3_scaffolded_mcq"
    scaffold_steps: list[str] = Field(min_length=1, max_length=5)
    scaffolded_mcq: QuizItem

    @model_validator(mode="after")
    def ensure_qcm(self):
        if self.scaffolded_mcq.type != "qcm":
            raise ValueError("A3 requires a four-choice QCM")
        return self


class TargetedRevision(_AdaptiveBase):
    strategy_id: Literal["A4_targeted_revision"] = "A4_targeted_revision"
    summary: str = Field(min_length=3, max_length=1200)
    key_points: list[str] = Field(min_length=1, max_length=5)
    common_error: str = Field(min_length=3)


AdaptiveRemediation = Annotated[
    GuidedHint | SimplifiedExplanation | WorkedExample | ScaffoldedMCQ | TargetedRevision,
    Field(discriminator="strategy_id"),
]

REMEDIATION_SCHEMAS = {
    ACTION_IDS[0]: GuidedHint,
    ACTION_IDS[1]: SimplifiedExplanation,
    ACTION_IDS[2]: WorkedExample,
    ACTION_IDS[3]: ScaffoldedMCQ,
    ACTION_IDS[4]: TargetedRevision,
}


def normalize_skill_label(label: str) -> str:
    text = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "competence"


def stable_skill_id(course_id: str, label: str) -> str:
    canonical = normalize_skill_label(label)
    digest = hashlib.sha256(f"{course_id}:{canonical}".encode()).hexdigest()[:12]
    return f"skill-{digest}"
