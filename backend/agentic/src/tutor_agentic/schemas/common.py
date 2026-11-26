"""Shared primitive types and enums."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictModel(BaseModel):
    """Inbound/outbound models we own: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ContractModel(BaseModel):
    """Models received from teammate services: additive fields are tolerated, types are not."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
]
LanguageTag = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")]


def bounded(max_length: int, min_length: int = 1) -> type[str]:
    """Bounded plain-text field (whitespace stripped)."""
    return Annotated[  # type: ignore[return-value]
        str, StringConstraints(min_length=min_length, max_length=max_length, strip_whitespace=True)
    ]


class Workflow(StrEnum):
    EXPERIENCE = "experience"
    ANSWER = "answer"
    LEARNING_PATH = "learning_path"
    TEACHER_REPORT = "teacher_report"
    PROGRESS = "progress"


class PresentationFormat(StrEnum):
    EXPLANATION = "explanation"
    QUIZ = "quiz"
    FLASHCARDS = "flashcards"
    CONCEPT_CARDS = "concept_cards"
    CONCEPT_MAP = "concept_map"
    STEPS = "steps"
    COMPARISON = "comparison"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class ActivityType(StrEnum):
    QUIZ = "quiz"
    EXERCISE = "exercise"
    FLASHCARDS = "flashcards"
    EXPLANATION = "explanation"
    REVISION = "revision"
    MINI_GAME = "mini_game"


class ColorVisionDeficiency(StrEnum):
    NONE = "none"
    PROTANOPIA = "protanopia"
    DEUTERANOPIA = "deuteranopia"
    TRITANOPIA = "tritanopia"


class AccessibilityPreferences(StrictModel):
    """Preferences the learner (or an authorized setting) declared explicitly.

    Nothing here is ever inferred from behaviour.
    """

    simplified_language: bool = False
    short_segments: bool = False
    reduced_visual_complexity: bool = False
    screen_reader_optimized: bool = False
    high_contrast: bool = False
    color_vision: ColorVisionDeficiency = ColorVisionDeficiency.NONE
    text_scale: float = Field(1.0, ge=1.0, le=2.0)

    def declared_needs(self) -> list[str]:
        needs = [
            name
            for name in (
                "simplified_language",
                "short_segments",
                "reduced_visual_complexity",
                "screen_reader_optimized",
                "high_contrast",
            )
            if getattr(self, name)
        ]
        if self.color_vision is not ColorVisionDeficiency.NONE:
            needs.append(f"color_vision:{self.color_vision.value}")
        return needs


class SourceRef(ContractModel):
    doc_id: Identifier
    chunk_id: Identifier
    page: int | None = Field(None, ge=1)
