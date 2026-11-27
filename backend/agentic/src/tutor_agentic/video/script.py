"""Converts educational content into a structured video script.

A script is a list of Slide objects. Each slide has:
  - title (shown as heading, also narrated)
  - body  (shown as text, narrated after the title)
  - duration_s (how long the slide stays on screen)

The script is derived deterministically from ExplanationContent, StepsContent,
FlashcardsContent or QuizContent — no LLM call needed here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Slide:
    title: str
    body: str
    duration_s: float = 5.0   # default on-screen time


# Average reading speed used to auto-compute slide duration (words per minute)
_WPM = 120.0
# Minimum and maximum slide duration in seconds
_MIN_S = 3.0
_MAX_S = 15.0


def _duration(text: str) -> float:
    words = len(text.split())
    secs = (words / _WPM) * 60
    return max(_MIN_S, min(_MAX_S, round(secs, 1)))


def script_from_content(content, topic: str = "") -> list[Slide]:
    """Build a slide script from any EducationalContent.

    Parameters
    ----------
    content : EducationalContent
        The validated content object from the graph state.
    topic : str
        Fallback title when the content carries no title.
    """
    kind = getattr(content, "kind", None)

    if kind == "explanation":
        return _from_explanation(content, topic)
    if kind == "steps":
        return _from_steps(content)
    if kind == "flashcards":
        return _from_flashcards(content)
    if kind == "quiz":
        return _from_quiz(content)
    if kind == "concept_cards":
        return _from_concept_cards(content)
    if kind == "remediation":
        return _from_remediation(content, topic)
    # Fallback: single-slide summary
    return [Slide(title=topic or "Résumé", body=str(content)[:500])]


def _from_explanation(content, topic: str) -> list[Slide]:
    slides: list[Slide] = []
    # Title slide
    title = getattr(content, "title", topic) or topic
    slides.append(Slide(title=title, body="", duration_s=3.0))
    # One slide per section
    for section in getattr(content, "sections", []):
        heading = getattr(section, "heading", None) or title
        body = getattr(section, "body", "") or ""
        slides.append(Slide(
            title=heading,
            body=body[:600],
            duration_s=_duration(heading + " " + body),
        ))
    # Key points slide
    kp = getattr(content, "key_points", [])
    if kp:
        slides.append(Slide(
            title="À retenir",
            body=" • ".join(kp[:6]),
            duration_s=_duration(" ".join(kp)),
        ))
    return slides or [Slide(title=title, body="", duration_s=3.0)]


def _from_steps(content) -> list[Slide]:
    slides: list[Slide] = []
    title = getattr(content, "title", "Étapes")
    slides.append(Slide(title=title, body="", duration_s=3.0))
    for i, step in enumerate(getattr(content, "steps", []), 1):
        slides.append(Slide(
            title=f"Étape {i} : {getattr(step, 'title', '')}",
            body=getattr(step, "detail", "")[:500],
            duration_s=_duration(getattr(step, "detail", "")),
        ))
    return slides


def _from_flashcards(content) -> list[Slide]:
    slides: list[Slide] = []
    title = getattr(content, "title", "Flashcards")
    slides.append(Slide(title=title, body="", duration_s=3.0))
    for card in getattr(content, "cards", [])[:12]:
        front = getattr(card, "front", "")
        back = getattr(card, "back", "")
        slides.append(Slide(
            title=front[:100],
            body=back[:400],
            duration_s=max(_MIN_S, _duration(front + " " + back)),
        ))
    return slides


def _from_quiz(content) -> list[Slide]:
    slides: list[Slide] = []
    title = getattr(content, "title", "Quiz")
    slides.append(Slide(title=title, body="", duration_s=3.0))
    for item in getattr(content, "items", [])[:8]:
        prompt = getattr(item, "prompt", "")
        expl = getattr(item, "explanation", "") or ""
        slides.append(Slide(
            title=prompt[:120],
            body=expl[:400],
            duration_s=max(_MIN_S, _duration(prompt + " " + expl)),
        ))
    return slides


def _from_concept_cards(content) -> list[Slide]:
    slides: list[Slide] = []
    title = getattr(content, "title", "Concepts")
    slides.append(Slide(title=title, body="", duration_s=3.0))
    for c in getattr(content, "concepts", [])[:10]:
        term = getattr(c, "term", "")
        defn = getattr(c, "definition", "")
        example = getattr(c, "example", "") or ""
        body = defn + (f"\n\nExemple : {example}" if example else "")
        slides.append(Slide(
            title=term[:100],
            body=body[:500],
            duration_s=_duration(defn + " " + example),
        ))
    return slides


def _from_remediation(content, topic: str) -> list[Slide]:
    slides: list[Slide] = []
    slides.append(Slide(title=topic or "Remédiation", body="", duration_s=3.0))
    diagnostic = getattr(content, "diagnostic", "") or ""
    if diagnostic:
        slides.append(Slide(title="Ce qui s'est passé", body=diagnostic[:400],
                            duration_s=_duration(diagnostic)))
    explanation = getattr(content, "explanation", "") or ""
    if explanation:
        for para in explanation.split("\n\n")[:4]:
            if para.strip():
                slides.append(Slide(title="Explication", body=para.strip()[:500],
                                    duration_s=_duration(para)))
    return slides
