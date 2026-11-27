"""Tests for the TTS text extractor (audio/extractor.py)."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tutor_agentic.audio.extractor import extract_text_for_tts, MAX_TTS_CHARS


# ---------------------------------------------------------------------------
# Helpers — fake block objects
# ---------------------------------------------------------------------------

class _Block:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def heading(text: str) -> _Block:
    return _Block(type="heading", text=text)


def text_block(text: str) -> _Block:
    return _Block(type="text", text=text)


def bullet_list(items: list[str]) -> _Block:
    return _Block(type="bullet_list", items=items)


def callout(text: str) -> _Block:
    return _Block(type="callout", text=text)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_blocks():
    assert extract_text_for_tts([]) == ""


def test_heading_included():
    result = extract_text_for_tts([heading("Titre principal")])
    assert "Titre principal" in result


def test_text_block_included():
    result = extract_text_for_tts([text_block("Corps du texte.")])
    assert "Corps du texte." in result


def test_bullet_list_included():
    result = extract_text_for_tts([bullet_list(["point 1", "point 2"])])
    assert "point 1" in result
    assert "point 2" in result


def test_callout_included():
    result = extract_text_for_tts([callout("Message important.")])
    assert "Message important." in result


def test_unknown_block_type_skipped():
    block = _Block(type="recommendation_card", recommendation_id="rec-1",
                   activity_type="quiz", difficulty="easy", topic="photo")
    result = extract_text_for_tts([block])
    assert result == ""


def test_max_chars_respected():
    long_text = "mot " * 2000
    block = text_block(long_text)
    result = extract_text_for_tts([block])
    assert len(result) <= MAX_TTS_CHARS


def test_multiple_blocks_concatenated():
    blocks = [heading("Titre"), text_block("Corps.")]
    result = extract_text_for_tts(blocks)
    assert "Titre" in result
    assert "Corps." in result


def test_quiz_prompts_included():
    class _QuizQ:
        def __init__(self, prompt):
            self.prompt = prompt
    block = _Block(type="quiz", questions=[_QuizQ("Qu'est-ce que la photosynthèse ?")])
    result = extract_text_for_tts([block])
    assert "photosynthèse" in result


def test_flashcard_fronts_included():
    class _Card:
        def __init__(self, front, back):
            self.front = front
            self.back = back
    block = _Block(type="flashcard_deck", title="Flash", cards=[_Card("Question", "Réponse")])
    result = extract_text_for_tts([block])
    assert "Question" in result
    # Back should NOT be included (student should think first)
    assert "Réponse" not in result
