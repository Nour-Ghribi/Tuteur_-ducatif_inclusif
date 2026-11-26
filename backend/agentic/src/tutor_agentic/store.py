"""Server-side record of activities issued to learners.

Answer keys never leave the backend: when a quiz is served, its items are kept here and answers
are graded against them. The in-memory implementation is process-local and bounded; a shared
store (e.g. Redis, owned by the infrastructure) can implement the same Protocol later.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Protocol

from .state import IssuedQuestion, RecommendationOutcome


class IssuedActivityStore(Protocol):
    def put_question(self, question: IssuedQuestion) -> None: ...

    def get_question(self, question_id: str, owner_ref: str) -> IssuedQuestion | None: ...

    def discard_question(self, question_id: str, owner_ref: str) -> None: ...

    def put_recommendation(self, owner_ref: str, recommendation: RecommendationOutcome) -> None: ...

    def get_recommendation(
        self, recommendation_id: str, owner_ref: str
    ) -> RecommendationOutcome | None: ...


class InMemoryIssuedActivityStore:
    def __init__(self, ttl_s: int = 3600, max_entries: int = 10_000) -> None:
        self._ttl_s = ttl_s
        self._max = max_entries
        self._entries: OrderedDict[tuple[str, str], tuple[float, object]] = OrderedDict()

    def _put(self, key: tuple[str, str], value: object) -> None:
        self._entries[key] = (time.monotonic() + self._ttl_s, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def _get(self, key: tuple[str, str]) -> object | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires < time.monotonic():
            del self._entries[key]
            return None
        return value

    def put_question(self, question: IssuedQuestion) -> None:
        self._put(("q:" + question.owner_ref, question.item.item_id), question)

    def get_question(self, question_id: str, owner_ref: str) -> IssuedQuestion | None:
        # Keyed by owner: a learner can only answer questions issued to them.
        return self._get(("q:" + owner_ref, question_id))  # type: ignore[return-value]

    def discard_question(self, question_id: str, owner_ref: str) -> None:
        """A graded question is single-attempt: its feedback reveals the answer key."""
        self._entries.pop(("q:" + owner_ref, question_id), None)

    def put_recommendation(self, owner_ref: str, recommendation: RecommendationOutcome) -> None:
        self._put(("r:" + owner_ref, recommendation.recommendation_id), recommendation)

    def get_recommendation(
        self, recommendation_id: str, owner_ref: str
    ) -> RecommendationOutcome | None:
        return self._get(("r:" + owner_ref, recommendation_id))  # type: ignore[return-value]
