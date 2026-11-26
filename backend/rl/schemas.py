"""HTTP contract for the RL recommendation service.

Mirrors tutor_agentic.integrations.contracts exactly so the agentic layer
can call this service when TUTOR_RL_SERVICE_URL is set.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------

Identifier = str  # 1-64 chars, [A-Za-z0-9_.:-]+
Difficulty = Literal["easy", "medium", "hard"]
ActivityType = Literal["quiz", "exercise", "flashcards", "explanation", "revision", "mini_game"]


# ---------------------------------------------------------------------------
# /v1/recommend
# ---------------------------------------------------------------------------

class LearnerFeatures(BaseModel):
    recent_scores: list[float] = Field(default_factory=list, max_length=20)
    avg_time_s: float | None = Field(None, ge=0)
    level: Difficulty | None = None
    last_outcome: Literal["correct", "incorrect", "skipped"] | None = None
    declared_needs: list[str] = Field(default_factory=list, max_length=20)


class ActivityOption(BaseModel):
    activity_type: ActivityType
    difficulty: Difficulty
    topic: str = Field(min_length=1, max_length=200)


class RecommendationRequest(BaseModel):
    student_ref: Identifier
    course_id: Identifier
    topic: str = Field(min_length=1, max_length=200)
    features: LearnerFeatures
    available_activities: list[ActivityOption] = Field(min_length=1, max_length=50)


class RecommendationResponse(BaseModel):
    recommendation_id: Identifier
    activity_type: ActivityType
    difficulty: Difficulty
    topic: str
    policy_version: str | None = None
    rationale: str | None = None
    simulated: bool = False


# ---------------------------------------------------------------------------
# /v1/outcomes
# ---------------------------------------------------------------------------

class OutcomeRequest(BaseModel):
    recommendation_id: Identifier
    student_ref: Identifier
    completed: bool
    score: float | None = Field(None, ge=0, le=1)
    time_spent_s: float | None = Field(None, ge=0)


class OutcomeResponse(BaseModel):
    accepted: bool
    simulated: bool = False
