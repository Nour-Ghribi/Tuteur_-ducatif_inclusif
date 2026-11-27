"""Tests for the student profile module (profiles/)."""
from __future__ import annotations

import pytest

from tutor_agentic.profiles.models import (
    AgeGroup,
    CognitiveNeed,
    HearingNeed,
    MotorNeed,
    ProfileCreateRequest,
    RenderingPreferences,
    SchoolLevel,
    StudentProfile,
    VisionNeed,
)
from tutor_agentic.profiles.defaults import needs_to_preferences, merge_with_request
from tutor_agentic.profiles.store import InMemoryProfileStore


# ---------------------------------------------------------------------------
# needs_to_preferences
# ---------------------------------------------------------------------------

def test_dyslexia_activates_audio_and_karaoke():
    profile = StudentProfile(
        subject_ref="s1",
        cognitive_need=CognitiveNeed.DYSLEXIA,
    )
    prefs = needs_to_preferences(profile)
    assert prefs.simplified_language is True
    assert prefs.audio_enabled is True
    assert prefs.karaoke_mode is True
    assert prefs.short_segments is True


def test_adhd_activates_short_segments_and_audio():
    profile = StudentProfile(subject_ref="s1", cognitive_need=CognitiveNeed.ADHD)
    prefs = needs_to_preferences(profile)
    assert prefs.short_segments is True
    assert prefs.audio_enabled is True


def test_autism_activates_high_contrast():
    profile = StudentProfile(subject_ref="s1", cognitive_need=CognitiveNeed.AUTISM)
    prefs = needs_to_preferences(profile)
    assert prefs.high_contrast is True
    assert prefs.reduced_visual_complexity is True


def test_blind_activates_screen_reader_and_audio():
    profile = StudentProfile(subject_ref="s1", vision_need=VisionNeed.BLIND)
    prefs = needs_to_preferences(profile)
    assert prefs.screen_reader_optimized is True
    assert prefs.audio_enabled is True


def test_protanopia_sets_color_vision():
    profile = StudentProfile(subject_ref="s1", vision_need=VisionNeed.PROTANOPIA)
    prefs = needs_to_preferences(profile)
    assert prefs.color_vision == "protanopia"


def test_no_needs_gives_defaults():
    profile = StudentProfile(subject_ref="s1")
    prefs = needs_to_preferences(profile)
    assert prefs.simplified_language is False
    assert prefs.audio_enabled is False
    assert prefs.color_vision == "none"


def test_multiple_needs_union():
    """Dyslexia + protanopia should activate both sets."""
    profile = StudentProfile(
        subject_ref="s1",
        cognitive_need=CognitiveNeed.DYSLEXIA,
        vision_need=VisionNeed.PROTANOPIA,
    )
    prefs = needs_to_preferences(profile)
    assert prefs.audio_enabled is True
    assert prefs.color_vision == "protanopia"


# ---------------------------------------------------------------------------
# merge_with_request
# ---------------------------------------------------------------------------

def test_merge_client_cannot_disable_profile_flag():
    profile_prefs = RenderingPreferences(simplified_language=True)
    client_dict = {"simplified_language": False, "short_segments": False}
    merged = merge_with_request(profile_prefs, client_dict)
    # Profile requires simplified_language=True; client cannot turn it off
    assert merged["simplified_language"] is True


def test_merge_client_can_add_new_flag():
    profile_prefs = RenderingPreferences(simplified_language=False)
    client_dict = {"simplified_language": True}
    merged = merge_with_request(profile_prefs, client_dict)
    assert merged["simplified_language"] is True


def test_merge_text_scale_takes_max():
    profile_prefs = RenderingPreferences(text_scale=1.5)
    client_dict = {"text_scale": 1.2}
    merged = merge_with_request(profile_prefs, client_dict)
    assert merged["text_scale"] == 1.5


def test_merge_color_vision_profile_wins():
    profile_prefs = RenderingPreferences(color_vision="deuteranopia")
    client_dict = {"color_vision": "none"}
    merged = merge_with_request(profile_prefs, client_dict)
    assert merged["color_vision"] == "deuteranopia"


# ---------------------------------------------------------------------------
# InMemoryProfileStore
# ---------------------------------------------------------------------------

def test_store_save_and_get():
    store = InMemoryProfileStore()
    profile = StudentProfile(
        subject_ref="student-test-1",
        age_group=AgeGroup.MIDDLE,
        school_level=SchoolLevel.MIDDLE,
        cognitive_need=CognitiveNeed.DYSLEXIA,
    )
    store.save(profile)
    retrieved = store.get("student-test-1")
    assert retrieved is not None
    assert retrieved.cognitive_need == CognitiveNeed.DYSLEXIA


def test_store_returns_none_for_unknown():
    store = InMemoryProfileStore()
    assert store.get("nonexistent") is None


def test_store_delete():
    store = InMemoryProfileStore()
    store.save(StudentProfile(subject_ref="s1"))
    store.delete("s1")
    assert store.get("s1") is None


def test_store_overwrite():
    store = InMemoryProfileStore()
    store.save(StudentProfile(subject_ref="s1", cognitive_need=CognitiveNeed.ADHD))
    store.save(StudentProfile(subject_ref="s1", cognitive_need=CognitiveNeed.DYSLEXIA))
    assert store.get("s1").cognitive_need == CognitiveNeed.DYSLEXIA
