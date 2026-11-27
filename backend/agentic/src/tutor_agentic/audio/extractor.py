"""Extracts plain readable text from UIBlocks for TTS synthesis.

Rules:
- Only text-bearing blocks are included (heading, text, bullet_list,
  callout, explanation sections, quiz question prompts, flashcard fronts).
- Quiz answer options, feedback scores and metadata are excluded —
  they are visual/interactive, not meant to be read aloud in sequence.
- Block order is preserved.
- Maximum total length is capped to avoid excessively long audio files.
"""
from __future__ import annotations

MAX_TTS_CHARS = 4000  # ~3–4 minutes of speech at normal speed


def extract_text_for_tts(blocks: list) -> str:
    """Convert a list of UIBlocks to a single plain-text string for TTS.

    Parameters
    ----------
    blocks : list[UIBlock]
        Blocks from a UISpec (already validated Python objects from schemas/ui.py).
    """
    parts: list[str] = []
    total = 0

    for block in blocks:
        btype = getattr(block, "type", None)

        if btype == "heading":
            text = getattr(block, "text", None) or ""
            if text and total + len(text) <= MAX_TTS_CHARS:
                parts.append(text)
                total += len(text)

        elif btype == "text":
            text = getattr(block, "text", "") or ""
            if total + len(text) <= MAX_TTS_CHARS:
                parts.append(text)
                total += len(text)
            else:
                remaining = MAX_TTS_CHARS - total
                if remaining > 50:
                    parts.append(text[:remaining])
                break

        elif btype == "bullet_list":
            items = getattr(block, "items", []) or []
            for item in items:
                if total + len(item) > MAX_TTS_CHARS:
                    break
                parts.append(f"• {item}")
                total += len(item)

        elif btype == "callout":
            text = getattr(block, "text", None) or ""
            if text and total + len(text) <= MAX_TTS_CHARS:
                parts.append(text)
                total += len(text)

        elif btype == "quiz":
            # Read question prompts only (no answer options)
            questions = getattr(block, "questions", []) or []
            for q in questions:
                prompt = getattr(q, "prompt", "") or ""
                if total + len(prompt) > MAX_TTS_CHARS:
                    break
                parts.append(prompt)
                total += len(prompt)

        elif btype == "flashcard_deck":
            # Read card fronts only (not answers — student should think first)
            cards = getattr(block, "cards", []) or []
            for card in cards:
                front = getattr(card, "front", "") or ""
                if total + len(front) > MAX_TTS_CHARS:
                    break
                parts.append(front)
                total += len(front)

        elif btype == "steps":
            steps = getattr(block, "steps", []) or []
            for i, step in enumerate(steps, 1):
                title = getattr(step, "title", "") or ""
                detail = getattr(step, "detail", "") or ""
                entry = f"Étape {i} : {title}. {detail}" if title else detail
                if total + len(entry) > MAX_TTS_CHARS:
                    break
                parts.append(entry)
                total += len(entry)

        elif btype == "concept_cards":
            concepts = getattr(block, "concepts", []) or []
            for c in concepts:
                term = getattr(c, "term", "") or ""
                defn = getattr(c, "definition", "") or ""
                entry = f"{term} : {defn}" if term else defn
                if total + len(entry) > MAX_TTS_CHARS:
                    break
                parts.append(entry)
                total += len(entry)

        if total >= MAX_TTS_CHARS:
            break

    return "\n\n".join(parts).strip()
