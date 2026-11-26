"""Wire contracts with teammate-owned services (version 1).

Every response model has ``simulated``: real services omit it (False); mocks set it to True so
simulated data can never be mistaken for real model output or real learner activity.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from ..schemas.common import (
    ActivityType,
    ColorVisionDeficiency,
    ContractModel,
    Difficulty,
    Identifier,
    LanguageTag,
    SourceRef,
    StrictModel,
    bounded,
)
from ..schemas.content import EducationalContent, GenerationTask

CONTRACT_VERSION = "1"


# --- RAG (owned by the RAG teammate) ---------------------------------------------------------


class RetrievalRequest(StrictModel):
    query: bounded(2000)
    course_id: Identifier
    top_k: int = Field(5, ge=1, le=20)
    language: LanguageTag | None = None


class RetrievedChunk(ContractModel):
    chunk_id: Identifier
    text: bounded(4000)
    source: SourceRef
    score: float = Field(ge=0)
    image_refs: list[Identifier] = Field(default_factory=list, max_length=10)  # opaque asset ids


class RetrievalResponse(ContractModel):
    chunks: list[RetrievedChunk] = Field(default_factory=list, max_length=20)
    index_version: bounded(100) | None = None
    simulated: bool = False


# --- GenAI (owned by the GenAI/multimodal teammate) ------------------------------------------


class ContextPassage(StrictModel):
    """Course excerpt passed as *untrusted data*, never merged into instructions."""

    passage_id: Identifier
    page: int | None = Field(None, ge=1)
    text: bounded(4000)
    trust: Literal["untrusted"] = "untrusted"


class GenerationPreferences(StrictModel):
    reading_level: Literal["simplified", "standard"] = "standard"
    max_segment_chars: int = Field(1200, ge=150, le=4000)
    language: LanguageTag | None = None  # None: follow the course language


class TopicAggregate(ContractModel):
    topic: bounded(200)
    attempts: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=1)
    median_time_s: float | None = Field(None, ge=0)
    common_error_tags: list[bounded(100)] = Field(default_factory=list, max_length=10)


class RemediationInput(StrictModel):
    question: bounded(1000)
    student_answer: bounded(2000)
    correct_answer: bounded(1000)
    history: list[bounded(300)] = Field(default_factory=list, max_length=10)


class GenerationRequest(StrictModel):
    task: GenerationTask
    topic: bounded(200)
    learner_request: bounded(2000) | None = None  # untrusted learner text
    context: list[ContextPassage] = Field(default_factory=list, max_length=20)
    report_aggregates: list[TopicAggregate] | None = None
    preferences: GenerationPreferences = Field(default_factory=GenerationPreferences)
    n_items: int | None = Field(None, ge=1, le=20)
    difficulty: Difficulty | None = None
    remediation: RemediationInput | None = None
    report_period: bounded(100) | None = None
    critic_feedback: list[Identifier] = Field(default_factory=list, max_length=20)


class GenerationResponse(ContractModel):
    content: EducationalContent
    prompt_version: bounded(100) | None = None
    model_id: bounded(100) | None = None
    pages_used: list[int] = Field(default_factory=list, max_length=50)
    invalid_citations: list[int] = Field(default_factory=list, max_length=50)
    simulated: bool = False


class AnswerEvaluationRequest(StrictModel):
    question_prompt: bounded(1000)
    reference_answer: bounded(1000)
    student_answer: bounded(2000)
    language: LanguageTag | None = None


class AnswerEvaluationResponse(ContractModel):
    is_correct: bool
    score: float = Field(ge=0, le=1)
    observed_errors: list[bounded(300)] = Field(default_factory=list, max_length=10)
    rationale: bounded(2000) | None = None
    model_id: bounded(100) | None = None
    simulated: bool = False


class IntentClassificationRequest(StrictModel):
    message: bounded(2000)
    allowed_intents: list[Identifier] = Field(min_length=1, max_length=20)


class IntentClassificationResponse(ContractModel):
    intent: Identifier
    confidence: float = Field(ge=0, le=1)
    simulated: bool = False


# --- Inclusion capabilities (expected from the GenAI/multimodal teammate; to be confirmed) -----


class ImageDescriptionRequest(StrictModel):
    image_ref: bounded(500)  # asset id or URL known to the content service
    language: LanguageTag | None = None
    detail: Literal["short", "long"] = "short"


class ImageDescriptionResponse(ContractModel):
    alt_text: bounded(300)
    long_description: bounded(2000) | None = None
    model_id: bounded(100) | None = None
    simulated: bool = False


class ColorAdaptationRequest(StrictModel):
    image_ref: bounded(500)
    deficiency: ColorVisionDeficiency

    @model_validator(mode="after")
    def _needs_deficiency(self) -> Self:
        if self.deficiency is ColorVisionDeficiency.NONE:
            raise ValueError("color adaptation requires a declared colour vision deficiency")
        return self


class ColorAdaptationResponse(ContractModel):
    adapted_image_ref: bounded(500)
    method: bounded(100) | None = None
    simulated: bool = False


# --- RL (owned by the RL teammate) ------------------------------------------------------------


class LearnerFeatures(StrictModel):
    recent_scores: list[float] = Field(default_factory=list, max_length=20)
    avg_time_s: float | None = Field(None, ge=0)
    level: Difficulty | None = None
    last_outcome: Literal["correct", "incorrect", "skipped"] | None = None
    declared_needs: list[bounded(64)] = Field(default_factory=list, max_length=10)


class ActivityOption(StrictModel):
    activity_type: ActivityType
    difficulty: Difficulty
    topic: bounded(200)


class RecommendationServiceRequest(StrictModel):
    student_ref: Identifier  # pseudonymous
    course_id: Identifier
    topic: bounded(200)
    features: LearnerFeatures
    available_activities: list[ActivityOption] = Field(min_length=1, max_length=50)


class RecommendationServiceResponse(ContractModel):
    recommendation_id: Identifier
    activity_type: ActivityType
    difficulty: Difficulty
    topic: bounded(200)
    policy_version: bounded(100) | None = None
    rationale: bounded(500) | None = None
    simulated: bool = False


class OutcomeReport(StrictModel):
    recommendation_id: Identifier
    student_ref: Identifier
    completed: bool
    score: float | None = Field(None, ge=0, le=1)
    time_spent_s: float | None = Field(None, ge=0)


class OutcomeAckResponse(ContractModel):
    accepted: bool
    simulated: bool = False


# --- Learning records / reporting (owner to be confirmed: RL or MLOps teammate) -----------------


class LearningSummariesRequest(StrictModel):
    class_id: Identifier
    course_id: Identifier | None = None
    period_start: date
    period_end: date


class LearningSummariesResponse(ContractModel):
    """Aggregates only. Per-learner records are never part of this contract."""

    class_id: Identifier
    period_start: date
    period_end: date
    learner_count: int = Field(ge=0)
    topics: list[TopicAggregate] = Field(default_factory=list, max_length=50)
    simulated: bool = False
