"""Student profile models.

A profile is established once during onboarding and updated by the student
(or a parent/teacher on their behalf). It is stored server-side and loaded
before every graph invocation — the client never supplies it.

Design constraints
------------------
- No PII: subject_ref is the only identity, pseudonymous.
- Declared, never inferred: cognitive/vision/hearing needs are what the
  student chose to tell us, not what we detected from behaviour.
- Rendering preferences are *derived* from declared needs via
  ``needs_to_preferences()`` but can be overridden per-request by the
  client's own AccessibilityPreferences (client can tighten, never expand).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AgeGroup(StrEnum):
    CHILD = "child"           # ~6-11
    MIDDLE = "middle"         # ~12-14
    HIGH = "high"             # ~15-18
    UNIVERSITY = "university" # ~18+
    ADULT = "adult"           # lifelong learning


class SchoolLevel(StrEnum):
    PRIMARY = "primary"
    MIDDLE = "middle"
    HIGH = "high"
    UNIVERSITY = "university"
    ADULT_LEARNING = "adult_learning"


class CognitiveNeed(StrEnum):
    NONE = "none"
    DYSLEXIA = "dyslexia"
    ADHD = "adhd"
    ADD = "add"
    AUTISM = "autism"
    DYSCALCULIA = "dyscalculia"


class VisionNeed(StrEnum):
    NONE = "none"
    LOW_VISION = "low_vision"
    PROTANOPIA = "protanopia"
    DEUTERANOPIA = "deuteranopia"
    TRITANOPIA = "tritanopia"
    BLIND = "blind"


class HearingNeed(StrEnum):
    NONE = "none"
    HARD_OF_HEARING = "hard_of_hearing"
    DEAF = "deaf"


class MotorNeed(StrEnum):
    NONE = "none"
    LIMITED_FINE_MOTOR = "limited_fine_motor"


# ---------------------------------------------------------------------------
# Rendering preferences (derived + overridable)
# ---------------------------------------------------------------------------

class RenderingPreferences(BaseModel):
    """What the platform will do by default for this student.

    These are auto-populated from declared needs (see defaults.py) but
    the student can override any field via the per-request
    AccessibilityPreferences sent from the frontend.
    """

    model_config = ConfigDict(extra="forbid")

    # Text
    simplified_language: bool = False
    short_segments: bool = False
    text_scale: float = Field(1.0, ge=1.0, le=2.0)

    # Visual
    high_contrast: bool = False
    reduced_visual_complexity: bool = False
    color_vision: Literal[
        "none", "protanopia", "deuteranopia", "tritanopia"
    ] = "none"

    # Screen reader
    screen_reader_optimized: bool = False

    # Audio
    audio_enabled: bool = False
    audio_speed: float = Field(1.0, ge=0.5, le=2.0)
    karaoke_mode: bool = False          # highlight word as audio plays

    def to_access_prefs_dict(self) -> dict:
        """Converts to a dict matching AccessibilityPreferences fields
        (subsetting — audio fields are not in AccessibilityPreferences yet)."""
        return {
            "simplified_language": self.simplified_language,
            "short_segments": self.short_segments,
            "reduced_visual_complexity": self.reduced_visual_complexity,
            "screen_reader_optimized": self.screen_reader_optimized,
            "high_contrast": self.high_contrast,
            "color_vision": self.color_vision,
            "text_scale": self.text_scale,
        }

    def declared_needs(self) -> list[str]:
        """Produces the declared_needs list fed to LearnerFeatures (RL context)."""
        needs: list[str] = []
        for flag in (
            "simplified_language",
            "short_segments",
            "reduced_visual_complexity",
            "screen_reader_optimized",
            "high_contrast",
            "audio_enabled",
            "karaoke_mode",
        ):
            if getattr(self, flag):
                needs.append(flag)
        if self.color_vision != "none":
            needs.append(f"color_vision:{self.color_vision}")
        return needs


# ---------------------------------------------------------------------------
# Main profile model
# ---------------------------------------------------------------------------

class StudentProfile(BaseModel):
    """Full server-side profile for one student.

    Loaded once per request by TutorService before graph invocation.
    Never sent to the client in full; only rendering_preferences are merged
    into the request.
    """

    model_config = ConfigDict(extra="forbid")

    subject_ref: str = Field(min_length=1, max_length=64)
    age_group: AgeGroup = AgeGroup.MIDDLE
    school_level: SchoolLevel = SchoolLevel.MIDDLE

    # Declared special needs
    cognitive_need: CognitiveNeed = CognitiveNeed.NONE
    vision_need: VisionNeed = VisionNeed.NONE
    hearing_need: HearingNeed = HearingNeed.NONE
    motor_need: MotorNeed = MotorNeed.NONE

    # Preferred interaction language (IETF tag: "ar", "fr", "en", "ar-TN", ...)
    language_preference: str = Field("fr", pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")

    # Auto-derived from declared needs, can be overridden
    rendering_preferences: RenderingPreferences = Field(
        default_factory=RenderingPreferences
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Request / response models for the profile API
# ---------------------------------------------------------------------------

class ProfileCreateRequest(BaseModel):
    """Body for POST /profile (onboarding)."""

    model_config = ConfigDict(extra="forbid")

    age_group: AgeGroup = AgeGroup.MIDDLE
    school_level: SchoolLevel = SchoolLevel.MIDDLE
    cognitive_need: CognitiveNeed = CognitiveNeed.NONE
    vision_need: VisionNeed = VisionNeed.NONE
    hearing_need: HearingNeed = HearingNeed.NONE
    motor_need: MotorNeed = MotorNeed.NONE
    language_preference: str = Field("fr", pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")
    # Optional manual override — if absent, derived from declared needs
    rendering_preferences: RenderingPreferences | None = None


class ProfileUpdateRequest(BaseModel):
    """Body for PUT /profile (partial update — only supplied fields change)."""

    model_config = ConfigDict(extra="forbid")

    age_group: AgeGroup | None = None
    school_level: SchoolLevel | None = None
    cognitive_need: CognitiveNeed | None = None
    vision_need: VisionNeed | None = None
    hearing_need: HearingNeed | None = None
    motor_need: MotorNeed | None = None
    language_preference: str | None = Field(
        None, pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$"
    )
    rendering_preferences: RenderingPreferences | None = None


class ProfileResponse(BaseModel):
    """Public view of a profile — omits timestamps, safe to send to the client."""

    subject_ref: str
    age_group: AgeGroup
    school_level: SchoolLevel
    cognitive_need: CognitiveNeed
    vision_need: VisionNeed
    hearing_need: HearingNeed
    motor_need: MotorNeed
    language_preference: str
    rendering_preferences: RenderingPreferences
    onboarding_complete: bool

    @classmethod
    def from_profile(cls, p: StudentProfile) -> "ProfileResponse":
        return cls(
            subject_ref=p.subject_ref,
            age_group=p.age_group,
            school_level=p.school_level,
            cognitive_need=p.cognitive_need,
            vision_need=p.vision_need,
            hearing_need=p.hearing_need,
            motor_need=p.motor_need,
            language_preference=p.language_preference,
            rendering_preferences=p.rendering_preferences,
            onboarding_complete=True,
        )
