"""Conversion between the GenAI module's output models (``tuteur.schemas``) and this layer's
content models. The GenAI module is accessed by attribute, so this file needs no import of it."""

from __future__ import annotations

from typing import Any

from ..schemas.common import Difficulty
from ..schemas.content import Flashcard, QuizItem, QuizOption

FR_TO_DIFFICULTY = {
    "facile": Difficulty.EASY,
    "moyen": Difficulty.MEDIUM,
    "difficile": Difficulty.HARD,
}
DIFFICULTY_TO_FR = {v: k for k, v in FR_TO_DIFFICULTY.items()}
LETTERS = "abcdef"


def question_for(topic: str, message: str | None) -> str:
    """Search/ask string for an explanation request: the selected topic anchors a vague message.

    Used both by the graph (retrieval query) and by the adapter (``Tutor.ask``) so the page checks
    see the same passages the GenAI module saw."""
    if not message or topic == message[:200]:
        return topic
    return f"{topic} — {message}"


def cut(value: str, limit: int) -> str:
    value = value.strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def to_quiz_item(item: Any, item_id: str) -> QuizItem:
    """qcm -> mcq, vrai_faux -> true_false, flashcard -> short_answer (graded against the answer)."""
    common = {
        "item_id": item_id,
        "prompt": cut(item.question, 1000),
        "explanation": cut(item.explanation, 2000) if item.explanation else None,
        "skill": cut(item.competence, 100) if item.competence else None,
        "difficulty": FR_TO_DIFFICULTY.get(item.difficulty),
        "source_pages": [p for p in item.source_pages if p >= 1][:20],
    }
    if item.type == "qcm":
        options = [
            QuizOption(option_id=LETTERS[i], text=cut(c, 500)) for i, c in enumerate(item.choices)
        ]
        correct = LETTERS[item.choices.index(item.answer)]
        return QuizItem(item_type="mcq", options=options, correct_option_id=correct, **common)
    if item.type == "vrai_faux":
        labels = list(item.choices) if len(item.choices) == 2 else ["Vrai", "Faux"]
        options = [
            QuizOption(option_id="true", text=labels[0]),
            QuizOption(option_id="false", text=labels[1]),
        ]
        correct = "true" if item.answer == "Vrai" else "false"
        return QuizItem(
            item_type="true_false", options=options, correct_option_id=correct, **common
        )
    return QuizItem(item_type="short_answer", reference_answer=cut(item.answer, 1000), **common)


def to_flashcard(item: Any) -> Flashcard:
    return Flashcard(front=cut(item.question, 300), back=cut(item.answer, 1000))
