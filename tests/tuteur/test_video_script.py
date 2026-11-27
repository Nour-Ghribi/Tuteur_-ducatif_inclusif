"""Tests for the video script generator (backend/agentic/.../video/script.py)."""
from __future__ import annotations

import sys
import os

# Make the agentic module importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend", "agentic", "src"))

from tutor_agentic.video.script import Slide, script_from_content, _duration


# ---------------------------------------------------------------------------
# _duration
# ---------------------------------------------------------------------------

def test_duration_short_text():
    d = _duration("Bonjour.")
    assert 3.0 <= d <= 15.0


def test_duration_long_text():
    d = _duration(" ".join(["mot"] * 100))
    assert d == 15.0  # capped at max


def test_duration_empty():
    d = _duration("")
    assert d == 3.0  # min


# ---------------------------------------------------------------------------
# script_from_content — explanation
# ---------------------------------------------------------------------------

class _FakeSection:
    def __init__(self, heading, body):
        self.heading = heading
        self.body = body


class _FakeExplanation:
    kind = "explanation"
    title = "La photosynthèse"

    def __init__(self):
        self.sections = [
            _FakeSection("Définition", "La photosynthèse est le processus..."),
            _FakeSection("Réactions", "Les réactions lumineuses produisent..."),
        ]
        self.key_points = ["Lumière → énergie", "CO2 + H2O → glucose"]


def test_explanation_produces_title_slide_plus_sections():
    content = _FakeExplanation()
    slides = script_from_content(content, "photosynthèse")
    # Title slide + 2 sections + key_points
    assert len(slides) >= 3
    assert slides[0].title == "La photosynthèse"
    assert slides[0].body == ""


def test_explanation_key_points_slide_last():
    content = _FakeExplanation()
    slides = script_from_content(content, "photosynthèse")
    last = slides[-1]
    assert "À retenir" in last.title
    assert "glucose" in last.body


# ---------------------------------------------------------------------------
# script_from_content — steps
# ---------------------------------------------------------------------------

class _FakeStep:
    def __init__(self, title, detail):
        self.title = title
        self.detail = detail


class _FakeSteps:
    kind = "steps"
    title = "Comment faire de la photosynthèse"

    def __init__(self):
        self.steps = [
            _FakeStep("Absorber la lumière", "Les chloroplastes absorbent..."),
            _FakeStep("Fixer le CO2", "Le cycle de Calvin fixe..."),
        ]


def test_steps_one_slide_per_step():
    slides = script_from_content(_FakeSteps(), "photosynthèse")
    assert len(slides) == 3  # title + 2 steps
    assert "Étape 1" in slides[1].title
    assert "Étape 2" in slides[2].title


# ---------------------------------------------------------------------------
# script_from_content — flashcards
# ---------------------------------------------------------------------------

class _FakeCard:
    def __init__(self, front, back):
        self.front = front
        self.back = back


class _FakeFlashcards:
    kind = "flashcards"
    title = "Flashcards photosynthèse"

    def __init__(self):
        self.cards = [_FakeCard(f"Q{i}", f"A{i}") for i in range(5)]


def test_flashcards_one_slide_per_card():
    slides = script_from_content(_FakeFlashcards(), "photo")
    assert len(slides) == 6  # title + 5 cards
    assert slides[1].title == "Q0"
    assert slides[1].body == "A0"


# ---------------------------------------------------------------------------
# Slide durations are within bounds
# ---------------------------------------------------------------------------

def test_all_slide_durations_in_bounds():
    content = _FakeExplanation()
    slides = script_from_content(content, "test")
    for slide in slides:
        assert 3.0 <= slide.duration_s <= 15.0
