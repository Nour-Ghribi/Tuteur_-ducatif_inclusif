"""Agent-to-UI contract (schema version 1.0).

The frontend renders *only* these block types, each mapped to a predefined React component.
All text is plain text: no HTML, Markdown or script is ever interpreted. The TypeScript mirror
lives in ``frontend/src/ui-schema`` (Phase 4) and must be kept in sync with this file.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .common import (
    ActivityType,
    Difficulty,
    Identifier,
    LanguageTag,
    SourceRef,
    StrictModel,
    bounded,
)

UI_SCHEMA_VERSION = "1.0"


class HeadingBlock(StrictModel):
    """Generated headings carry ``text``; system headings carry a localizable ``text_code``."""

    type: Literal["heading"] = "heading"
    text: bounded(200) | None = None
    text_code: Identifier | None = None
    level: int = Field(2, ge=1, le=3)

    @model_validator(mode="after")
    def _has_label(self) -> Self:
        if (self.text is None) == (self.text_code is None):
            raise ValueError("provide exactly one of text or text_code")
        return self


class TextBlock(StrictModel):
    type: Literal["text"] = "text"
    text: bounded(4000)


class BulletListBlock(StrictModel):
    type: Literal["bullet_list"] = "bullet_list"
    items: list[bounded(500)] = Field(min_length=1, max_length=20)


class CalloutBlock(StrictModel):
    type: Literal["callout"] = "callout"
    tone: Literal["info", "success", "warning", "error"] = "info"
    message_code: Identifier | None = None  # localized by the frontend
    text: bounded(1000) | None = None


class FlashcardView(StrictModel):
    front: bounded(300)
    back: bounded(1000)


class FlashcardDeckBlock(StrictModel):
    type: Literal["flashcard_deck"] = "flashcard_deck"
    title: bounded(200)
    cards: list[FlashcardView] = Field(min_length=1, max_length=30)


class QuizOptionView(StrictModel):
    option_id: Identifier
    text: bounded(500)


class QuizQuestionView(StrictModel):
    """A question as shown to the learner. It never carries the answer key."""

    question_id: Identifier
    item_type: Literal["mcq", "true_false", "short_answer"]
    prompt: bounded(1000)
    options: list[QuizOptionView] = Field(default_factory=list, max_length=6)


class QuizBlock(StrictModel):
    type: Literal["quiz"] = "quiz"
    title: bounded(200)
    questions: list[QuizQuestionView] = Field(min_length=1, max_length=20)


class QuizFeedbackBlock(StrictModel):
    type: Literal["quiz_feedback"] = "quiz_feedback"
    question_id: Identifier
    is_correct: bool
    score: float = Field(ge=0, le=1)
    correct_option_id: Identifier | None = None
    explanation: bounded(2000) | None = None
    observed_errors: list[bounded(300)] = Field(default_factory=list, max_length=10)


class ConceptView(StrictModel):
    term: bounded(120)
    definition: bounded(1000)
    example: bounded(500) | None = None


class ConceptCardsBlock(StrictModel):
    type: Literal["concept_cards"] = "concept_cards"
    title: bounded(200)
    concepts: list[ConceptView] = Field(min_length=1, max_length=20)


class StepView(StrictModel):
    title: bounded(200)
    detail: bounded(2000)


class StepsBlock(StrictModel):
    type: Literal["steps"] = "steps"
    title: bounded(200)
    steps: list[StepView] = Field(min_length=1, max_length=15)


class ComparisonRowView(StrictModel):
    criterion: bounded(120)
    values: list[bounded(500)] = Field(min_length=2, max_length=5)


class ComparisonTableBlock(StrictModel):
    type: Literal["comparison_table"] = "comparison_table"
    title: bounded(200)
    columns: list[bounded(120)] = Field(min_length=2, max_length=5)
    rows: list[ComparisonRowView] = Field(min_length=1, max_length=15)


class MapNodeView(StrictModel):
    node_id: Identifier
    label: bounded(120)


class MapEdgeView(StrictModel):
    source: Identifier
    target: Identifier
    label: bounded(80) | None = None


class ConceptMapBlock(StrictModel):
    type: Literal["concept_map"] = "concept_map"
    title: bounded(200)
    central_node_id: Identifier
    nodes: list[MapNodeView] = Field(min_length=2, max_length=40)
    edges: list[MapEdgeView] = Field(default_factory=list, max_length=80)


class ProgressBlock(StrictModel):
    type: Literal["progress"] = "progress"
    label_code: Identifier
    value: float = Field(ge=0, le=1)


class RecommendationCardBlock(StrictModel):
    type: Literal["recommendation_card"] = "recommendation_card"
    recommendation_id: Identifier
    activity_type: ActivityType
    difficulty: Difficulty
    topic: bounded(200)
    rationale: bounded(500) | None = None
    source: Literal["policy", "fallback"] = "policy"


class Metric(StrictModel):
    label_code: Identifier  # e.g. "learner_count", "success_rate"; localized by the frontend
    value: float
    unit: Literal["count", "ratio", "seconds"]


class MetricGridBlock(StrictModel):
    type: Literal["metric_grid"] = "metric_grid"
    metrics: list[Metric] = Field(min_length=1, max_length=12)


class Bar(StrictModel):
    label: bounded(120)
    value: float = Field(ge=0)


class BarChartBlock(StrictModel):
    """Rendered with a mandatory table alternative for screen readers."""

    type: Literal["bar_chart"] = "bar_chart"
    title_code: Identifier
    value_unit: Literal["ratio", "count"]
    bars: list[Bar] = Field(min_length=1, max_length=30)


class ImageBlock(StrictModel):
    """Course figure. ``alt_text`` is mandatory; ``adapted`` marks a colour-vision variant."""

    type: Literal["image"] = "image"
    asset_id: Identifier
    alt_text: bounded(300) | None = None
    long_description: bounded(2000) | None = None
    adapted: bool = False
    description_source: Literal["model", "placeholder"] = "model"

    @model_validator(mode="after")
    def _needs_alt_text(self) -> Self:
        if self.description_source == "model" and not self.alt_text:
            raise ValueError("a described image needs alt_text")
        return self


class FallbackBlock(StrictModel):
    type: Literal["fallback"] = "fallback"
    reason_code: Identifier
    text: bounded(2000) | None = None


UIBlock = Annotated[
    HeadingBlock
    | TextBlock
    | BulletListBlock
    | CalloutBlock
    | FlashcardDeckBlock
    | QuizBlock
    | QuizFeedbackBlock
    | ConceptCardsBlock
    | StepsBlock
    | ComparisonTableBlock
    | ConceptMapBlock
    | ProgressBlock
    | RecommendationCardBlock
    | MetricGridBlock
    | BarChartBlock
    | ImageBlock
    | FallbackBlock,
    Field(discriminator="type"),
]

ALLOWED_BLOCK_TYPES: frozenset[str] = frozenset(
    {
        "heading",
        "text",
        "bullet_list",
        "callout",
        "flashcard_deck",
        "quiz",
        "quiz_feedback",
        "concept_cards",
        "steps",
        "comparison_table",
        "concept_map",
        "progress",
        "recommendation_card",
        "metric_grid",
        "bar_chart",
        "image",
        "fallback",
    }
)


class VerificationReport(StrictModel):
    """What was actually checked. ``passed`` only covers the checks listed in ``checks_run``."""

    checks_run: list[Identifier] = Field(default_factory=list)
    passed: bool
    issues: list[Identifier] = Field(default_factory=list, max_length=20)
    notes: list[Identifier] = Field(default_factory=list, max_length=20)  # non-blocking findings


class UIMeta(StrictModel):
    language: LanguageTag | None = None
    grounding: Literal["context_provided", "no_context", "not_applicable"] = "not_applicable"
    sources: list[SourceRef] = Field(default_factory=list, max_length=20)
    verification: VerificationReport | None = None
    simulated: bool = False
    simulated_services: list[Identifier] = Field(default_factory=list)
    fallback_used: bool = False
    warnings: list[Identifier] = Field(default_factory=list, max_length=20)
    prompt_version: bounded(100) | None = None
    model_id: bounded(100) | None = None


class UISpec(StrictModel):
    schema_version: Literal["1.0"] = UI_SCHEMA_VERSION
    blocks: list[UIBlock] = Field(min_length=1, max_length=40)
    meta: UIMeta = Field(default_factory=UIMeta)
