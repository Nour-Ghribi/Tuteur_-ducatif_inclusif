"""Formats de sortie structurés de la GenAI (validés par Pydantic)."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Difficulty = Literal["facile", "moyen", "difficile"]
QuestionType = Literal["qcm", "vrai_faux", "flashcard"]


class QuizItem(BaseModel):
    type: QuestionType
    question: str
    choices: list[str] = Field(default_factory=list)
    answer: str
    explanation: str
    difficulty: Difficulty
    competence: str = Field(description="Compétence ou notion évaluée, en quelques mots")
    source_pages: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_answer(self):
        if self.type == "qcm":
            if len(self.choices) != 4:
                raise ValueError("un QCM doit avoir exactement 4 choix")
            if self.answer not in self.choices:
                raise ValueError("la réponse d'un QCM doit être l'un des choix")
        if self.type == "vrai_faux" and self.answer not in ("Vrai", "Faux"):
            raise ValueError("la réponse d'un vrai/faux doit être 'Vrai' ou 'Faux'")
        return self


class Quiz(BaseModel):
    items: list[QuizItem]


class Remediation(BaseModel):
    diagnostic: str = Field(description="Confusion probable de l'élève, formulée avec bienveillance")
    explanation: str = Field(description="Réexplication ciblée de la notion")
    exercise: QuizItem = Field(description="Nouvel exercice, plus simple, ciblant la confusion")


class Answer(BaseModel):
    text: str = Field(description="Réponse affichée (citations invalides retirées)")
    raw_text: str = Field("", description="Réponse brute du LLM (pour l'évaluation)")
    invalid_citations: list[int] = Field(default_factory=list, description="Pages citées absentes des passages")
    sources: list[dict]
    contexts: list[str] = Field(default_factory=list, description="Passages donnés au LLM (pour l'évaluation)")
    context_pages: list[int] = Field(default_factory=list)
    prompt: str
