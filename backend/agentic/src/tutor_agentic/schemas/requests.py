"""Inbound request models (validated by FastAPI before anything reaches the graph).

Learner identity is never taken from the body: it comes from the authenticated principal.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, Self

from pydantic import Field, model_validator

from .common import (
    AccessibilityPreferences,
    Identifier,
    LanguageTag,
    PresentationFormat,
    StrictModel,
    bounded,
)

MAX_REPORT_PERIOD = timedelta(days=366)


class PreviousActivity(StrictModel):
    activity_id: Identifier
    outcome: Literal["correct", "incorrect", "skipped"]


class ExperienceRequest(StrictModel):
    message: bounded(2000)
    course_id: Identifier
    topic: bounded(200) | None = None
    requested_format: PresentationFormat | None = None
    language: LanguageTag | None = None
    preferences: AccessibilityPreferences = Field(default_factory=AccessibilityPreferences)
    previous_activity: PreviousActivity | None = None
    adaptive: bool = True


class StudentAnswer(StrictModel):
    selected_option_id: Identifier | None = None
    text: bounded(2000) | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.selected_option_id is None) == (self.text is None):
            raise ValueError("provide exactly one of selected_option_id or text")
        return self


class AnswerSubmission(StrictModel):
    question_id: Identifier
    answer: StudentAnswer
    time_spent_s: float | None = Field(None, ge=0, le=7200)
    language: LanguageTag | None = None
    preferences: AccessibilityPreferences = Field(default_factory=AccessibilityPreferences)
    request_recommendation: bool = True


class RecommendationRequest(StrictModel):
    course_id: Identifier
    topic: bounded(200)
    language: LanguageTag | None = None
    preferences: AccessibilityPreferences = Field(default_factory=AccessibilityPreferences)


class ActivityOutcome(StrictModel):
    completed: bool
    score: float | None = Field(None, ge=0, le=1)
    time_spent_s: float | None = Field(None, ge=0, le=7200)


class TeacherReportRequest(StrictModel):
    class_id: Identifier
    course_id: Identifier | None = None
    period_start: date
    period_end: date
    language: LanguageTag | None = None

    @model_validator(mode="after")
    def _valid_period(self) -> Self:
        if self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end")
        if self.period_end > date.today():
            raise ValueError("period_end cannot be in the future")
        if self.period_end - self.period_start > MAX_REPORT_PERIOD:
            raise ValueError("the report period cannot exceed 366 days")
        return self
