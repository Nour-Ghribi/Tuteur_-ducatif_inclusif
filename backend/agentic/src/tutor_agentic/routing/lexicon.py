"""Language data for deterministic intent detection.

Patterns are matched against lower-cased, accent-stripped text. Adding a language means adding
entries here; the router logic stays language-agnostic.
"""

from __future__ import annotations

from .intents import Intent

INTENT_PATTERNS: dict[Intent, tuple[str, ...]] = {
    Intent.FLASHCARDS: (
        r"\bflash ?cards?\b",
        r"\bcartes? (memoire|de revision|flash)\b",
        r"\bfiches? (de revision|memoire)\b",
    ),
    Intent.CONCEPT_MAP: (
        r"\bmind ?maps?\b",
        r"\bconcept maps?\b",
        r"\bcartes? (mentales?|conceptuelles?|heuristiques?)\b",
    ),
    Intent.STEPS: (
        r"\bstep[- ]by[- ]step\b",
        r"\bguide me\b",
        r"\betape par etape\b",
        r"\bpas a pas\b",
        r"\bguide[- ]moi\b",
    ),
    Intent.COMPARISON: (
        r"\bcompar",
        r"\bdifferences? (between|entre)\b",
        r"\bversus\b",
        r"\bvs\.?\s",
    ),
    Intent.CONCEPT_CARDS: (
        r"\b(key|main|core) concepts?\b",
        r"\bconcepts? (cles?|principaux|importants)\b",
        r"\bnotions? (cles?|principales|importantes)\b",
    ),
    Intent.NEW_EXERCISE: (
        r"\b(another|new|one more|different) (exercise|question|problem)\b",
        r"\b(un )?(autre|nouvel?|encore un) exercice\b",
        r"\bune autre question\b",
    ),
    Intent.QUIZ: (
        r"\bquiz",
        r"\bqcm\b",
        r"\btest me\b",
        r"\b(generate|give me|create|ask me|write)\b.*\bquestions?\b",
        r"\binterroge[- ]moi\b",
        r"\bteste[- ]moi\b",
        r"\b(genere|donne|cree|pose|propose)[a-z]*\b.*\bquestions?\b",
    ),
    Intent.EXPLAIN: (
        r"\bexplain",
        r"\bsummar",
        r"\bwhat (is|are)\b",
        r"\bhelp me understand\b",
        r"\bexpliqu",
        r"\bresum",
        r"\bc'?est quoi\b",
        r"\bqu'?est[- ]ce que\b",
    ),
}

# When several specific intents match and no classifier settles it, the first one listed wins.
PRIORITY: tuple[Intent, ...] = (
    Intent.NEW_EXERCISE,
    Intent.QUIZ,
    Intent.FLASHCARDS,
    Intent.CONCEPT_MAP,
    Intent.STEPS,
    Intent.COMPARISON,
    Intent.CONCEPT_CARDS,
    Intent.EXPLAIN,
)

NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
}  # fmt: skip

COUNTABLE_NOUNS = (
    r"(questions?|items?|flash ?cards?|cards?|cartes?|fiches?|exercises?|exercices?|concepts?|"
    r"notions?|qcm)"
)
