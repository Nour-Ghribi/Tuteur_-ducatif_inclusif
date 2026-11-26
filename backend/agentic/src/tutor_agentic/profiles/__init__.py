"""Student profile management module."""

from .defaults import needs_to_preferences, merge_with_request, SCHOOL_LEVEL_DIFFICULTY, SCHOOL_LEVEL_TONE
from .models import (
    AgeGroup,
    CognitiveNeed,
    HearingNeed,
    MotorNeed,
    ProfileCreateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    RenderingPreferences,
    SchoolLevel,
    StudentProfile,
    VisionNeed,
)
from .router import create_profile_router
from .store import InMemoryProfileStore, ProfileStore, SQLiteProfileStore

__all__ = [
    # models
    "AgeGroup",
    "CognitiveNeed",
    "HearingNeed",
    "MotorNeed",
    "ProfileCreateRequest",
    "ProfileResponse",
    "ProfileUpdateRequest",
    "RenderingPreferences",
    "SchoolLevel",
    "StudentProfile",
    "VisionNeed",
    # defaults
    "needs_to_preferences",
    "merge_with_request",
    "SCHOOL_LEVEL_DIFFICULTY",
    "SCHOOL_LEVEL_TONE",
    # store
    "InMemoryProfileStore",
    "ProfileStore",
    "SQLiteProfileStore",
    # router
    "create_profile_router",
]
