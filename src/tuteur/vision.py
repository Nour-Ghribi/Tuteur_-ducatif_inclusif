"""VLM image describer for RAG ingestion.

Calls any OpenAI-compatible vision API (Ollama+LLaVA, Gemini, OpenAI GPT-4o,
Qwen2-VL, etc.) to generate a textual description of each image extracted from
a course PDF. The descriptions become searchable chunks in ChromaDB alongside
the page text, so queries about diagram content are answered from the index.

Design constraints
------------------
- Optional: if VISION_MODEL is not configured the describer returns None and
  the pipeline skips image description silently.
- Idempotent: a description file (.txt) is written next to the PNG; if it already
  exists the VLM is not called again (re-ingesting the same PDF is cheap).
- Multilingual: the prompt asks the VLM to respond in the course language.
- Grounded: the description is marked as untrusted in chunk metadata —
  the generation layer treats it as retrieved context, never as ground truth.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Prompt sent to the VLM for every image.
# The VLM is asked to output two lines (ALT / LONG) so we can split them.
_SYSTEM = (
    "You describe course figures for a student who cannot see them. "
    "Be factual: only describe what is visible. "
    "Do not invent information absent from the image. "
    "Respond in {language}."
)
_USER = (
    "Describe this course figure in two parts:\n"
    "ALT: one sentence of 25 words maximum — suitable as alt text.\n"
    "LONG: a detailed description (up to 200 words) of what the figure shows, "
    "including all visible labels, arrows, legends and relationships. "
    "If a detail is illegible, say so."
)


def _parse_response(text: str) -> tuple[str, str]:
    """Split 'ALT: … LONG: …' into (alt, long). Falls back gracefully."""
    alt, long_desc = text.strip(), ""
    if "ALT:" in text:
        _, _, tail = text.partition("ALT:")
        alt_part, _, long_part = tail.partition("LONG:")
        alt = alt_part.strip()
        long_desc = long_part.strip()
    return (alt or "image")[:300], (long_desc or "")[:2000]


class VLMDescriber:
    """Calls a vision-capable LLM to describe a PNG image file.

    Parameters
    ----------
    model : str
        Model name, e.g. "llava", "gpt-4o", "gemini-2.0-flash", "qwen2-vl".
    base_url : str | None
        OpenAI-compatible base URL. None uses the OpenAI default.
    api_key : str
        API key. Use "ollama" for local Ollama instances.
    language : str
        IETF language tag for the description language, e.g. "fr", "ar", "en".
    timeout : float
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key: str = "none",
        language: str = "fr",
        timeout: float = 60.0,
    ) -> None:
        from openai import OpenAI  # lazy import — heavy dependency

        self._model = model
        self._language = language
        self._client = OpenAI(
            base_url=base_url or None,
            api_key=api_key,
            timeout=timeout,
            max_retries=1,
        )

    def describe(self, image_path: Path) -> tuple[str, str]:
        """Returns (alt_text, long_description) for the given PNG.

        Raises on API errors — callers should handle and skip gracefully.
        """
        data = base64.b64encode(image_path.read_bytes()).decode()
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": _SYSTEM.format(language=self._language),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _USER},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{data}"},
                        },
                    ],
                },
            ],
        )
        raw = response.choices[0].message.content or ""
        return _parse_response(raw)


def describe_page_images(
    image_paths: list[Path],
    describer: VLMDescriber,
    *,
    force: bool = False,
) -> list[tuple[Path, str, str]]:
    """Describe a list of PNG images, skipping already-described ones.

    Returns a list of (path, alt_text, long_description) for successfully
    described images. Failures are logged and skipped.

    The description is cached as a `.txt` sidecar file next to the PNG so that
    re-ingesting the same PDF never makes redundant VLM calls.

    Parameters
    ----------
    image_paths : list[Path]
        PNG files extracted from one PDF page.
    describer : VLMDescriber
        Configured VLM client.
    force : bool
        If True, re-describe even if a sidecar already exists.
    """
    results: list[tuple[Path, str, str]] = []
    for path in image_paths:
        sidecar = path.with_suffix(".txt")
        if not force and sidecar.exists():
            # Use cached description
            cached = sidecar.read_text(encoding="utf-8")
            alt, long_desc = _parse_response(cached)
            results.append((path, alt, long_desc))
            continue
        try:
            alt, long_desc = describer.describe(path)
            # Write sidecar for future re-ingestions
            sidecar.write_text(f"ALT: {alt}\nLONG: {long_desc}", encoding="utf-8")
            results.append((path, alt, long_desc))
            log.debug("Described %s: %s", path.name, alt[:60])
        except Exception as exc:
            log.warning("VLM description failed for %s: %s", path.name, exc)
            # Keep image in the pipeline without a description
    return results


def make_describer_from_settings(settings) -> VLMDescriber | None:
    """Builds a VLMDescriber from tuteur Settings. Returns None if not configured."""
    model = getattr(settings, "vision_model", "") or ""
    if not model:
        return None
    return VLMDescriber(
        model=model,
        base_url=getattr(settings, "vision_base_url", None) or None,
        api_key=getattr(settings, "vision_api_key", "none") or "none",
        language=getattr(settings, "vision_language", "fr") or "fr",
        timeout=getattr(settings, "vision_timeout_s", 60.0),
    )
