"""Intent routing: explicit choice > deterministic rules > optional classifier > default."""

from __future__ import annotations

import re
import unicodedata

from ..errors import AdapterError
from ..integrations.contracts import IntentClassificationRequest
from ..integrations.ports import IntentClassifierPort
from ..schemas.common import PresentationFormat
from . import lexicon
from .intents import FORMAT_TO_INTENT, Intent, IntentDecision

_COMPILED = {
    intent: tuple(re.compile(p) for p in patterns)
    for intent, patterns in lexicon.INTENT_PATTERNS.items()
}
_COUNT = re.compile(
    rf"\b(\d{{1,2}}|{'|'.join(lexicon.NUMBER_WORDS)})\s+{lexicon.COUNTABLE_NOUNS}\b"
)


def normalize(message: str) -> str:
    decomposed = unicodedata.normalize("NFKD", message.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[’`]", "'", stripped)


def extract_count(normalized: str) -> int | None:
    match = _COUNT.search(normalized)
    if not match:
        return None
    raw = match.group(1)
    value = int(raw) if raw.isdigit() else lexicon.NUMBER_WORDS[raw]
    return min(max(value, 1), 20)


def match_intents(normalized: str) -> list[Intent]:
    found = [i for i, patterns in _COMPILED.items() if any(p.search(normalized) for p in patterns)]
    return sorted(found, key=lexicon.PRIORITY.index)


class IntentRouter:
    def __init__(
        self, classifier: IntentClassifierPort | None = None, min_confidence: float = 0.6
    ) -> None:
        self._classifier = classifier
        self._min_confidence = min_confidence

    async def decide(
        self, message: str, requested_format: PresentationFormat | None = None
    ) -> IntentDecision:
        normalized = normalize(message)
        count = extract_count(normalized)

        if requested_format is not None:
            return IntentDecision(
                intent=FORMAT_TO_INTENT[requested_format], source="explicit", n_items=count
            )

        candidates = match_intents(normalized)
        # A specific format ("explain it step by step") is more informative than "explain".
        specific = [c for c in candidates if c is not Intent.EXPLAIN]
        if len(specific) == 1:
            return IntentDecision(
                intent=specific[0], source="rule", candidates=candidates, n_items=count
            )
        if not specific and candidates:
            return IntentDecision(
                intent=Intent.EXPLAIN, source="rule", candidates=candidates, n_items=count
            )

        # Ambiguous (several specific intents) or unknown (nothing matched).
        allowed = specific or list(Intent)
        classified, warning = await self._classify(message, allowed)
        if classified is not None:
            return IntentDecision(
                intent=classified, source="classifier", candidates=specific, n_items=count
            )
        if specific:
            return IntentDecision(
                intent=specific[0],
                source="rule",
                candidates=specific,
                n_items=count,
                warning=warning or "intent_ambiguous",
            )
        return IntentDecision(
            intent=Intent.EXPLAIN,
            source="default",
            n_items=count,
            warning=warning or "intent_defaulted",
        )

    async def _classify(
        self, message: str, allowed: list[Intent]
    ) -> tuple[Intent | None, str | None]:
        if self._classifier is None:
            return None, None
        try:
            result = await self._classifier.classify(
                IntentClassificationRequest(
                    message=message, allowed_intents=[i.value for i in allowed]
                )
            )
        except AdapterError:
            return None, "intent_classifier_unavailable"
        # The classifier can only choose among allowed intents; anything else is ignored.
        if result.intent not in {i.value for i in allowed}:
            return None, "intent_classifier_rejected"
        if result.confidence < self._min_confidence:
            return None, "intent_classifier_low_confidence"
        return Intent(result.intent), None
