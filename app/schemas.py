"""Schémas d'entrée et de sortie de l'API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Modèle de base refusant les champs inattendus."""

    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictModel):
    status: Literal["ok"]
    service: str
    environment: str
    mode: Literal["simulation"]


class QuizRequest(StrictModel):
    subject: str = Field(min_length=2, max_length=80, examples=["Mathématiques"])
    topic: str = Field(min_length=2, max_length=120, examples=["Les fractions"])
    difficulty: Literal["facile", "moyen", "difficile"] = "moyen"
    number_of_questions: int = Field(default=3, ge=1, le=10)
    accessibility_needs: list[str] = Field(default_factory=list, max_length=5)


class QuizQuestion(StrictModel):
    id: int
    prompt: str
    choices: list[str]
    correct_answer: str


class QuizResponse(StrictModel):
    quiz_id: str
    subject: str
    topic: str
    difficulty: str
    questions: list[QuizQuestion]
    accessibility_support: list[str]
    is_simulated: Literal[True]


class StudentAnswerRequest(StrictModel):
    quiz_id: str = Field(min_length=1, max_length=100)
    question_id: int = Field(ge=1)
    answer: str = Field(min_length=1, max_length=300)
    expected_answer: str = Field(min_length=1, max_length=300)


class StudentAnswerResponse(StrictModel):
    quiz_id: str
    question_id: int
    is_correct: bool
    score: float = Field(ge=0, le=1)
    feedback: str
    is_simulated: Literal[True]


class NextActivityRequest(StrictModel):
    performance_score: float = Field(ge=0, le=1)
    attempts: int = Field(default=1, ge=1, le=100)
    current_topic: str = Field(min_length=2, max_length=120)
    accessibility_needs: list[str] = Field(default_factory=list, max_length=5)


class NextActivityResponse(StrictModel):
    activity_type: Literal["remediation", "practice", "challenge"]
    difficulty: Literal["facile", "moyen", "difficile"]
    reason: str
    topic: str
    accessibility_support: list[str]
    policy: Literal["mock-rules-v1"]
    is_simulated: Literal[True]

