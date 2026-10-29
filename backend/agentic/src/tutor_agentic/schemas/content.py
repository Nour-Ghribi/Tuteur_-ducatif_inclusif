"""Educational content returned by the GenAI service.

Content is *data*, separate from presentation: the UI planner decides how it is rendered.
Validation here is what turns malformed model output into a predictable error.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .common import ContractModel, Difficulty, Identifier, bounded


class GenerationTask(StrEnum):
    EXPLANATION = "explanation"
    QUIZ = "quiz"
    FLASHCARDS = "flashcards"
    CONCEPT_CARDS = "concept_cards"
    CONCEPT_MAP = "concept_map"
    STEPS = "steps"
    COMPARISON = "comparison"
    REMEDIATION = "remediation"
    REPORT_SUMMARY = "report_summary"


def _unique(values: list[str], what: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {what}")


class Section(ContractModel):
    heading: bounded(200) | None = None
    body: bounded(4000)


class ExplanationContent(ContractModel):
    kind: Literal["explanation"] = "explanation"
    title: bounded(200)
    sections: list[Section] = Field(min_length=1, max_length=12)
    key_points: list[bounded(300)] = Field(default_factory=list, max_length=10)


class QuizOption(ContractModel):
    option_id: Identifier
    text: bounded(500)


class QuizItem(ContractModel):
    item_id: Identifier
    item_type: Literal["mcq", "true_false", "short_answer"]
    prompt: bounded(1000)
    options: list[QuizOption] = Field(default_factory=list, max_length=6)
    correct_option_id: Identifier | None = None
    reference_answer: bounded(1000) | None = None
    explanation: bounded(2000) | None = None
    skill: bounded(100) | None = None
    difficulty: Difficulty | None = None
    source_pages: list[int] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _check_answer_key(self) -> Self:
        option_ids = [o.option_id for o in self.options]
        _unique(option_ids, "option ids")
        if self.item_type == "short_answer":
            if self.options or not self.reference_answer:
                raise ValueError("short_answer needs a reference_answer and no options")
            return self
        expected = (2, 2) if self.item_type == "true_false" else (2, 6)
        if not expected[0] <= len(self.options) <= expected[1]:
            raise ValueError(f"{self.item_type} has an invalid number of options")
        if self.correct_option_id not in option_ids:
            raise ValueError("correct_option_id must reference one of the options")
        return self


class QuizContent(ContractModel):
    kind: Literal["quiz"] = "quiz"
    title: bounded(200)
    items: list[QuizItem] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _unique_items(self) -> Self:
        _unique([i.item_id for i in self.items], "item ids")
        return self


class Flashcard(ContractModel):
    front: bounded(300)
    back: bounded(1000)


class FlashcardsContent(ContractModel):
    kind: Literal["flashcards"] = "flashcards"
    title: bounded(200)
    cards: list[Flashcard] = Field(min_length=1, max_length=30)


class Concept(ContractModel):
    term: bounded(120)
    definition: bounded(1000)
    example: bounded(500) | None = None


class ConceptCardsContent(ContractModel):
    kind: Literal["concept_cards"] = "concept_cards"
    title: bounded(200)
    concepts: list[Concept] = Field(min_length=1, max_length=20)


class MapNode(ContractModel):
    node_id: Identifier
    label: bounded(120)


class MapEdge(ContractModel):
    source: Identifier
    target: Identifier
    label: bounded(80) | None = None


class ConceptMapContent(ContractModel):
    kind: Literal["concept_map"] = "concept_map"
    title: bounded(200)
    central_node_id: Identifier
    nodes: list[MapNode] = Field(min_length=2, max_length=40)
    edges: list[MapEdge] = Field(default_factory=list, max_length=80)

    @model_validator(mode="after")
    def _consistent_graph(self) -> Self:
        ids = [n.node_id for n in self.nodes]
        _unique(ids, "node ids")
        known = set(ids)
        if self.central_node_id not in known:
            raise ValueError("central_node_id must reference a node")
        if any(e.source not in known or e.target not in known for e in self.edges):
            raise ValueError("edges must reference existing nodes")
        return self


class Step(ContractModel):
    title: bounded(200)
    detail: bounded(2000)


class StepsContent(ContractModel):
    kind: Literal["steps"] = "steps"
    title: bounded(200)
    steps: list[Step] = Field(min_length=1, max_length=15)


class ComparisonRow(ContractModel):
    criterion: bounded(120)
    values: list[bounded(500)] = Field(min_length=2, max_length=5)


class ComparisonContent(ContractModel):
    kind: Literal["comparison"] = "comparison"
    title: bounded(200)
    items: list[bounded(120)] = Field(min_length=2, max_length=5)
    rows: list[ComparisonRow] = Field(min_length=1, max_length=15)

    @model_validator(mode="after")
    def _rectangular(self) -> Self:
        if any(len(r.values) != len(self.items) for r in self.rows):
            raise ValueError("each comparison row needs one value per compared item")
        return self


class RemediationContent(ContractModel):
    """Targeted re-explanation plus one exercise. ``diagnostic`` is a hypothesis, never a fact."""

    kind: Literal["remediation"] = "remediation"
    diagnostic: bounded(1000) | None = None
    explanation: bounded(4000)
    exercise: QuizContent


class ReportSummaryContent(ContractModel):
    kind: Literal["report_summary"] = "report_summary"
    summary: bounded(3000)
    recurring_difficulties: list[bounded(300)] = Field(default_factory=list, max_length=10)


EducationalContent = Annotated[
    ExplanationContent
    | QuizContent
    | FlashcardsContent
    | ConceptCardsContent
    | ConceptMapContent
    | StepsContent
    | ComparisonContent
    | RemediationContent
    | ReportSummaryContent,
    Field(discriminator="kind"),
]
