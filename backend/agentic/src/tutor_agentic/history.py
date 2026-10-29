"""Per-learner history kept server-side (pseudonymous ``student_ref`` only).

It feeds two consumers: the remediation prompt (recent errors on a competence) and the RL
service (recent scores). The learner never supplies it, so it cannot be forged from the browser.
The in-memory store is bounded and process-local; a shared store can implement the same Protocol.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from typing import Protocol

from pydantic import BaseModel, Field

MAX_ATTEMPTS_PER_LEARNER = 50
RECURRING_THRESHOLD = 2  # wrong answers on one competence before a pattern is called "recurring"


class Attempt(BaseModel):
    topic: str
    competence: str | None = None
    correct: bool
    score: float = Field(ge=0, le=1)
    time_spent_s: float | None = None
    observed_errors: list[str] = Field(default_factory=list)
    at: float = Field(default_factory=time.time)


class HistorySnapshot(BaseModel):
    """What the graph is allowed to see: aggregates and short labels, not raw answers."""

    recent_scores: list[float] = Field(default_factory=list)
    avg_time_s: float | None = None
    error_labels: list[str] = Field(default_factory=list)
    attempts_total: int = 0


class StudentHistoryStore(Protocol):
    def record(self, student_ref: str, attempt: Attempt) -> None: ...

    def snapshot(
        self, student_ref: str, *, topic: str | None, competence: str | None
    ) -> HistorySnapshot: ...

    def wrong_on_competence(self, student_ref: str, competence: str | None) -> int: ...


class InMemoryStudentHistory:
    def __init__(self, max_students: int = 10_000) -> None:
        self._data: OrderedDict[str, deque[Attempt]] = OrderedDict()
        self._max = max_students

    def record(self, student_ref: str, attempt: Attempt) -> None:
        attempts = self._data.setdefault(student_ref, deque(maxlen=MAX_ATTEMPTS_PER_LEARNER))
        attempts.append(attempt)
        self._data.move_to_end(student_ref)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def _attempts(self, student_ref: str) -> list[Attempt]:
        return list(self._data.get(student_ref, ()))

    def snapshot(
        self, student_ref: str, *, topic: str | None, competence: str | None
    ) -> HistorySnapshot:
        attempts = self._attempts(student_ref)
        scoped = [a for a in attempts if topic is None or a.topic == topic] or attempts
        times = [a.time_spent_s for a in scoped if a.time_spent_s is not None]
        labels = [
            f"{a.competence or a.topic}: {', '.join(a.observed_errors) or 'erreur'}"[:300]
            for a in attempts
            if not a.correct and (competence is None or a.competence == competence)
        ]
        return HistorySnapshot(
            recent_scores=[a.score for a in scoped][-10:],
            avg_time_s=sum(times) / len(times) if times else None,
            error_labels=labels[-5:],
            attempts_total=len(attempts),
        )

    def wrong_on_competence(self, student_ref: str, competence: str | None) -> int:
        return sum(
            1 for a in self._attempts(student_ref) if not a.correct and a.competence == competence
        )
