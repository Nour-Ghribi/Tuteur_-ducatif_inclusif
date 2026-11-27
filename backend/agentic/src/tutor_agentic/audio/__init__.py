"""Audio generation module for the agentic tutor layer."""

from .extractor import extract_text_for_tts
from .tts import TTSAdapter, TTSResult, WordTimestamp, make_tts_from_settings

__all__ = [
    "TTSAdapter",
    "TTSResult",
    "WordTimestamp",
    "extract_text_for_tts",
    "make_tts_from_settings",
]
