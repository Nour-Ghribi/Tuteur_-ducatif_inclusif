"""Data models for engagement snapshots and badge events.

These are stored in the student ledger DB alongside the RL tables.
They are computed after each session, never inferred in real-time.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Engagement snapshot
# ---------------------------------------------------------------------------

EngagementTier = Literal["low", "medium", "high"]


def _tier(score: float) -> EngagementTier:
    if score >= 0.7:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"


class EngagementSnapshot(BaseModel):
    """Computed engagement scores for one student, produced after each session.

    curiosity_score    — how much the student explores beyond required tasks.
    persistence_score  — how much the student keeps trying after failure.
    autonomy_score     — how independently the student navigates the platform.

    All scores are floats in [0, 1]. Tiers are derived labels for display.
    """
    student_id: str
    computed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    curiosity_score: float = Field(0.0, ge=0.0, le=1.0)
    persistence_score: float = Field(0.0, ge=0.0, le=1.0)
    autonomy_score: float = Field(0.0, ge=0.0, le=1.0)

    # Number of sessions / attempts used to compute — for confidence display
    sessions_used: int = Field(0, ge=0)
    attempts_used: int = Field(0, ge=0)

    @property
    def curiosity_tier(self) -> EngagementTier:
        return _tier(self.curiosity_score)

    @property
    def persistence_tier(self) -> EngagementTier:
        return _tier(self.persistence_score)

    @property
    def autonomy_tier(self) -> EngagementTier:
        return _tier(self.autonomy_score)

    def to_declared_needs_tags(self) -> list[str]:
        """Produces tags fed to LearnerFeatures.declared_needs for RL context."""
        return [
            f"curiosity:{self.curiosity_tier}",
            f"persistence:{self.persistence_tier}",
            f"autonomy:{self.autonomy_tier}",
        ]


# ---------------------------------------------------------------------------
# Badge event
# ---------------------------------------------------------------------------

BadgeTier = Literal["bronze", "silver", "gold", "special"]


class BadgeEvent(BaseModel):
    """A badge earned by a student at a point in time."""
    id: str
    student_id: str
    badge_id: str
    tier: BadgeTier = "bronze"
    earned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # JSON-serialisable context (e.g. which skill triggered it)
    context: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Badge definition (loaded from badges.yaml)
# ---------------------------------------------------------------------------

class BadgeDefinition(BaseModel):
    id: str
    label_fr: str
    label_ar: str = ""
    label_en: str = ""
    icon: str = "star"
    tier: BadgeTier = "bronze"
    description_fr: str = ""
    trigger_type: Literal[
        "threshold",        # metric >= value
        "streak",           # consecutive active days
        "skill_accuracy",   # skill accuracy >= value with min_attempts
        "first_time",       # first occurrence of event
    ]
    trigger_metric: str           # e.g. "attempts_total", "curiosity_score"
    trigger_value: float
    trigger_min_attempts: int = 0  # only for skill_accuracy
