"""Tests for the engagement computer and badge engine."""
from __future__ import annotations

import pytest

from tuteur.adaptive.engagement.models import EngagementSnapshot, _tier
from tuteur.adaptive.engagement.badge_engine import BadgeEngine, _load_definitions
from tuteur.adaptive.engagement.computer import EngagementComputer
from tuteur.adaptive.database import SQLiteRepository


# ---------------------------------------------------------------------------
# _tier helper
# ---------------------------------------------------------------------------

def test_tier_low():
    assert _tier(0.1) == "low"


def test_tier_medium():
    assert _tier(0.5) == "medium"


def test_tier_high():
    assert _tier(0.8) == "high"


def test_tier_boundary_low_medium():
    assert _tier(0.3) == "medium"


def test_tier_boundary_medium_high():
    assert _tier(0.7) == "high"


# ---------------------------------------------------------------------------
# EngagementSnapshot
# ---------------------------------------------------------------------------

def test_snapshot_tiers():
    snap = EngagementSnapshot(
        student_id="s1",
        curiosity_score=0.8,
        persistence_score=0.4,
        autonomy_score=0.1,
    )
    assert snap.curiosity_tier == "high"
    assert snap.persistence_tier == "medium"
    assert snap.autonomy_tier == "low"


def test_snapshot_declared_needs_tags():
    snap = EngagementSnapshot(
        student_id="s1",
        curiosity_score=0.8,
        persistence_score=0.5,
        autonomy_score=0.2,
    )
    tags = snap.to_declared_needs_tags()
    assert "curiosity:high" in tags
    assert "persistence:medium" in tags
    assert "autonomy:low" in tags


# ---------------------------------------------------------------------------
# Badge definitions load
# ---------------------------------------------------------------------------

def test_badge_definitions_load():
    defs = _load_definitions()
    assert len(defs) > 10
    ids = [d.id for d in defs]
    assert "first_step" in ids
    assert "curious_explorer" in ids
    assert "resilient" in ids


def test_badge_definitions_have_multilingual_labels():
    defs = _load_definitions()
    for d in defs:
        assert d.label_fr, f"Badge {d.id} missing label_fr"


# ---------------------------------------------------------------------------
# BadgeEngine — first_step badge on empty DB
# ---------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    return SQLiteRepository(tmp_path / "test.db")


def test_first_step_not_earned_on_empty_db(repo):
    engine = BadgeEngine(repo)
    snap = EngagementSnapshot(student_id="s1", attempts_used=0)
    new_badges = engine.evaluate_after_session("s1", snap)
    # first_step requires attempts_total >= 1; on empty DB it's 0
    ids = [b.badge_id for b in new_badges]
    assert "first_step" not in ids


def test_no_duplicate_badges(repo):
    """Calling evaluate twice never duplicates a badge."""
    engine = BadgeEngine(repo)
    snap = EngagementSnapshot(
        student_id="s1",
        curiosity_score=0.9,
        persistence_score=0.9,
        autonomy_score=0.9,
        attempts_used=0,
    )
    first = engine.evaluate_after_session("s1", snap)
    second = engine.evaluate_after_session("s1", snap)
    # Any badge awarded in first must NOT appear in second
    first_ids = {b.badge_id for b in first}
    second_ids = {b.badge_id for b in second}
    assert first_ids.isdisjoint(second_ids)


def test_earned_badges_returns_all(repo):
    engine = BadgeEngine(repo)
    snap = EngagementSnapshot(student_id="s1", attempts_used=0)
    engine.evaluate_after_session("s1", snap)
    all_badges = engine.earned_badges("s1")
    assert isinstance(all_badges, list)
