from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from ..schemas.common import PresentationFormat
from ..schemas.content import GenerationTask


class Intent(StrEnum):
    EXPLAIN = "explain"
    QUIZ = "quiz"
    FLASHCARDS = "flashcards"
    CONCEPT_CARDS = "concept_cards"
    CONCEPT_MAP = "concept_map"
    STEPS = "steps"
    COMPARISON = "comparison"
    NEW_EXERCISE = "new_exercise"


FORMAT_TO_INTENT: dict[PresentationFormat, Intent] = {
    PresentationFormat.EXPLANATION: Intent.EXPLAIN,
    PresentationFormat.QUIZ: Intent.QUIZ,
    PresentationFormat.FLASHCARDS: Intent.FLASHCARDS,
    PresentationFormat.CONCEPT_CARDS: Intent.CONCEPT_CARDS,
    PresentationFormat.CONCEPT_MAP: Intent.CONCEPT_MAP,
    PresentationFormat.STEPS: Intent.STEPS,
    PresentationFormat.COMPARISON: Intent.COMPARISON,
}

INTENT_TO_TASK: dict[Intent, GenerationTask] = {
    Intent.EXPLAIN: GenerationTask.EXPLANATION,
    Intent.QUIZ: GenerationTask.QUIZ,
    Intent.FLASHCARDS: GenerationTask.FLASHCARDS,
    Intent.CONCEPT_CARDS: GenerationTask.CONCEPT_CARDS,
    Intent.CONCEPT_MAP: GenerationTask.CONCEPT_MAP,
    Intent.STEPS: GenerationTask.STEPS,
    Intent.COMPARISON: GenerationTask.COMPARISON,
    Intent.NEW_EXERCISE: GenerationTask.QUIZ,
}

DEFAULT_ITEM_COUNT: dict[GenerationTask, int] = {
    GenerationTask.QUIZ: 5,
    GenerationTask.FLASHCARDS: 8,
    GenerationTask.CONCEPT_CARDS: 6,
}


class IntentDecision(BaseModel):
    intent: Intent
    source: Literal["explicit", "rule", "classifier", "default"]
    candidates: list[Intent] = Field(default_factory=list)
    n_items: int | None = Field(None, ge=1, le=20)
    warning: str | None = None
