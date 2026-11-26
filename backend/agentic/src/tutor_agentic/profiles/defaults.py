"""Maps declared special needs to default rendering preferences.

This is the single place that answers: "given what a student told us about
themselves, what should we turn on by default?"

Rules are additive: each need contributes its flags, the union wins.
The student can override any flag via the per-request AccessibilityPreferences
(frontend preferences panel) — but only to tighten, not to disable what their
declared need requires (e.g. a dyslexic student cannot accidentally turn off
simplified_language from the wrong toggle — that would require a profile update).
"""

from __future__ import annotations

from .models import (
    CognitiveNeed,
    HearingNeed,
    MotorNeed,
    RenderingPreferences,
    SchoolLevel,
    StudentProfile,
    VisionNeed,
)


# ---------------------------------------------------------------------------
# Need → preference mappings
# ---------------------------------------------------------------------------

_COGNITIVE: dict[CognitiveNeed, dict] = {
    CognitiveNeed.NONE: {},
    CognitiveNeed.DYSLEXIA: {
        "simplified_language": True,
        "short_segments": True,
        "audio_enabled": True,
        "karaoke_mode": True,
        "text_scale": 1.2,
    },
    CognitiveNeed.ADHD: {
        "short_segments": True,
        "audio_enabled": True,
        "reduced_visual_complexity": True,
    },
    CognitiveNeed.ADD: {
        "short_segments": True,
        "audio_enabled": True,
    },
    CognitiveNeed.AUTISM: {
        "simplified_language": True,
        "short_segments": True,
        "reduced_visual_complexity": True,
        "high_contrast": True,
    },
    CognitiveNeed.DYSCALCULIA: {
        "simplified_language": True,
        "short_segments": True,
    },
}

_VISION: dict[VisionNeed, dict] = {
    VisionNeed.NONE: {},
    VisionNeed.LOW_VISION: {
        "text_scale": 1.5,
        "high_contrast": True,
        "screen_reader_optimized": True,
    },
    VisionNeed.PROTANOPIA: {"color_vision": "protanopia"},
    VisionNeed.DEUTERANOPIA: {"color_vision": "deuteranopia"},
    VisionNeed.TRITANOPIA: {"color_vision": "tritanopia"},
    VisionNeed.BLIND: {
        "screen_reader_optimized": True,
        "audio_enabled": True,
        "reduced_visual_complexity": True,
    },
}

_HEARING: dict[HearingNeed, dict] = {
    HearingNeed.NONE: {},
    HearingNeed.HARD_OF_HEARING: {
        "simplified_language": True,
    },
    HearingNeed.DEAF: {
        "simplified_language": True,
        "short_segments": True,
    },
}

_MOTOR: dict[MotorNeed, dict] = {
    MotorNeed.NONE: {},
    MotorNeed.LIMITED_FINE_MOTOR: {
        # Larger touch targets handled on the frontend via text_scale
        "text_scale": 1.3,
    },
}

# School level → tone label used by prompt templates
SCHOOL_LEVEL_TONE: dict[SchoolLevel, str] = {
    SchoolLevel.PRIMARY: "primary",
    SchoolLevel.MIDDLE: "middle",
    SchoolLevel.HIGH: "high",
    SchoolLevel.UNIVERSITY: "university",
    SchoolLevel.ADULT_LEARNING: "adult",
}

# School level → default difficulty baseline for the RL model
SCHOOL_LEVEL_DIFFICULTY: dict[SchoolLevel, str] = {
    SchoolLevel.PRIMARY: "easy",
    SchoolLevel.MIDDLE: "easy",
    SchoolLevel.HIGH: "medium",
    SchoolLevel.UNIVERSITY: "medium",
    SchoolLevel.ADULT_LEARNING: "medium",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def needs_to_preferences(profile: StudentProfile) -> RenderingPreferences:
    """Derives the full RenderingPreferences from a student's declared needs.

    Called during onboarding (when no manual override is provided) and
    whenever a need field changes via PUT /profile.
    """
    merged: dict = {}

    for source in (
        _COGNITIVE.get(profile.cognitive_need, {}),
        _VISION.get(profile.vision_need, {}),
        _HEARING.get(profile.hearing_need, {}),
        _MOTOR.get(profile.motor_need, {}),
    ):
        for key, value in source.items():
            # Booleans: True wins. Floats: take the max. Strings: last writer wins.
            if key not in merged:
                merged[key] = value
            elif isinstance(value, bool):
                merged[key] = merged[key] or value
            elif isinstance(value, float):
                merged[key] = max(merged[key], value)
            else:
                merged[key] = value

    return RenderingPreferences(**merged)


def merge_with_request(
    profile_prefs: RenderingPreferences,
    request_prefs_dict: dict,
) -> dict:
    """Merges server-side profile preferences with client-supplied overrides.

    The client can tighten (turn more things on) but not disable what the
    profile requires. Returns a dict suitable for AccessibilityPreferences(**...).
    """
    result = profile_prefs.to_access_prefs_dict()

    for key, client_value in request_prefs_dict.items():
        if key not in result:
            continue
        profile_value = result[key]
        if isinstance(profile_value, bool):
            # Client can only turn ON, not turn off a profile-required flag
            result[key] = profile_value or client_value
        elif isinstance(profile_value, float):
            result[key] = max(profile_value, client_value)
        elif isinstance(profile_value, str):
            # color_vision: profile wins if it set a deficiency
            result[key] = profile_value if profile_value != "none" else client_value

    return result
