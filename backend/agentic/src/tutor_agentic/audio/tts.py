"""TTS (Text-To-Speech) adapter for the agentic layer.

Calls any OpenAI-compatible TTS endpoint:
  - Kokoro TTS (open source, local, fast, AR/FR/EN)  → http://localhost:8880/v1
  - OpenAI TTS (tts-1 / tts-1-hd)                   → https://api.openai.com/v1
  - Any other compatible service

The adapter returns:
  - raw audio bytes (MP3)
  - optional word-level timestamps for karaoke mode

Karaoke timestamps
------------------
The OpenAI TTS API does not currently return word-level timestamps.
When karaoke=True we fall back to a simple linear interpolation that splits
the text into words and distributes the total duration evenly.
This is a best-effort approximation; a future version can use Whisper
forced-alignment or Kokoro's native timestamp output when available.
"""
from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class WordTimestamp:
    word: str
    start_ms: int
    end_ms: int


@dataclass
class TTSResult:
    audio_bytes: bytes           # MP3 / WAV depending on provider
    duration_ms: int             # estimated total duration
    word_timestamps: list[WordTimestamp] = field(default_factory=list)
    model_id: str = ""


class TTSAdapter:
    """Calls an OpenAI-compatible /v1/audio/speech endpoint.

    Parameters
    ----------
    model : str
        TTS model name, e.g. "tts-1", "kokoro", "tts-1-hd".
    voice : str
        Voice identifier, e.g. "alloy", "nova", "af_heart" (Kokoro).
    base_url : str | None
        Base URL of the TTS service. None uses OpenAI's default.
    api_key : str
        API key. Use "kokoro" or "none" for local services.
    speed : float
        Speech rate multiplier (0.5–2.0). Applied per-request.
    timeout : float
        Per-request timeout in seconds.
    """

    # Average speaking rate in words per minute, used for linear interpolation
    _WPM = 150.0

    def __init__(
        self,
        model: str = "tts-1",
        voice: str = "alloy",
        base_url: str | None = None,
        api_key: str = "none",
        speed: float = 1.0,
        timeout: float = 30.0,
    ) -> None:
        from openai import OpenAI  # lazy import
        self._model = model
        self._voice = voice
        self._speed = speed
        self._client = OpenAI(
            base_url=base_url or None,
            api_key=api_key,
            timeout=timeout,
            max_retries=1,
        )

    def synthesize(
        self,
        text: str,
        speed: float | None = None,
        karaoke: bool = False,
    ) -> TTSResult:
        """Convert text to speech.

        Parameters
        ----------
        text : str
            Plain text to synthesize (no SSML, no HTML).
        speed : float | None
            Override the adapter-level speed for this request.
        karaoke : bool
            If True, generate word-level timestamps via linear interpolation.
        """
        effective_speed = max(0.5, min(2.0, speed if speed is not None else self._speed))

        response = self._client.audio.speech.create(
            model=self._model,
            voice=self._voice,
            input=text,
            speed=effective_speed,
            response_format="mp3",
        )
        audio_bytes = response.read()

        # Estimate duration: bytes / (128 kbps / 8) = seconds
        duration_ms = max(1, int(len(audio_bytes) / (128_000 / 8) * 1000))

        timestamps: list[WordTimestamp] = []
        if karaoke:
            timestamps = self._linear_timestamps(text, duration_ms)

        return TTSResult(
            audio_bytes=audio_bytes,
            duration_ms=duration_ms,
            word_timestamps=timestamps,
            model_id=self._model,
        )

    @staticmethod
    def _linear_timestamps(text: str, duration_ms: int) -> list[WordTimestamp]:
        """Distribute duration evenly across words (best-effort approximation)."""
        words = [w for w in re.split(r"\s+", text.strip()) if w]
        if not words:
            return []
        ms_per_word = duration_ms / len(words)
        result: list[WordTimestamp] = []
        for i, word in enumerate(words):
            start = int(i * ms_per_word)
            end = int((i + 1) * ms_per_word)
            result.append(WordTimestamp(word=word, start_ms=start, end_ms=end))
        return result


def make_tts_from_settings(settings) -> TTSAdapter | None:
    """Build a TTSAdapter from agentic Settings. Returns None if not configured."""
    model = getattr(settings, "tts_model", "") or ""
    if not model:
        return None
    return TTSAdapter(
        model=model,
        voice=getattr(settings, "tts_voice", "alloy") or "alloy",
        base_url=getattr(settings, "tts_base_url", None) or None,
        api_key=(
            getattr(settings, "tts_api_key", None).get_secret_value()
            if getattr(settings, "tts_api_key", None)
            else "none"
        ),
        speed=getattr(settings, "tts_speed", 1.0),
        timeout=getattr(settings, "tts_timeout_s", 30.0),
    )
