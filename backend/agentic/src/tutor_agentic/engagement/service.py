"""EngagementService: post-session hook that computes engagement and awards badges.

Called by TutorService after a session ends. It is completely optional —
if the SQLite ledger is unavailable (mock mode), it no-ops gracefully.

The result (snapshot + new badges) is:
1. Stored in the DB for history / trend charts.
2. Returned so the response can include a BadgeToastBlock for newly earned badges.
3. Used to build the LearnerFeatures.declared_needs tags for the RL context.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class SessionEngagementResult:
    """What was computed and awarded after a session."""
    snapshot: "EngagementSnapshot | None"      # type: ignore[name-defined]
    new_badges: list                            # list[BadgeEvent]
    declared_needs_tags: list[str]             # for LearnerFeatures


class EngagementService:
    """Thin wrapper that runs EngagementComputer + BadgeEngine after a session."""

    def __init__(self, ledger_path: str | Path | None = None) -> None:
        self._ledger_path = Path(ledger_path) if ledger_path else None
        self._repo = None
        self._computer = None
        self._engine = None

        if self._ledger_path:
            try:
                from tuteur.adaptive.database import SQLiteRepository
                from tuteur.adaptive.engagement import BadgeEngine, EngagementComputer
                self._repo = SQLiteRepository(self._ledger_path)
                self._computer = EngagementComputer(self._repo)
                self._engine = BadgeEngine(self._repo)
            except ImportError as exc:
                log.warning(
                    "EngagementService disabled: tuteur library not installed (%s)", exc
                )

    @property
    def available(self) -> bool:
        return self._computer is not None and self._engine is not None

    def run_after_session(self, student_id: str) -> SessionEngagementResult:
        """Compute engagement + evaluate badges. Returns empty result if unavailable."""
        if not self.available:
            return SessionEngagementResult(
                snapshot=None, new_badges=[], declared_needs_tags=[]
            )
        try:
            snapshot = self._computer.compute(student_id)      # type: ignore[union-attr]
            self._repo.save_engagement_snapshot(snapshot)       # type: ignore[union-attr]
            new_badges = self._engine.evaluate_after_session(   # type: ignore[union-attr]
                student_id, snapshot
            )
            tags = snapshot.to_declared_needs_tags()
            return SessionEngagementResult(
                snapshot=snapshot,
                new_badges=new_badges,
                declared_needs_tags=tags,
            )
        except Exception as exc:
            log.warning("EngagementService.run_after_session failed: %s", exc)
            return SessionEngagementResult(
                snapshot=None, new_badges=[], declared_needs_tags=[]
            )

    def latest_snapshot(self, student_id: str):
        """Returns the most recent engagement snapshot, or None."""
        if not self.available:
            return None
        try:
            return self._repo.latest_engagement_snapshot(student_id)   # type: ignore[union-attr]
        except Exception as exc:
            log.warning("EngagementService.latest_snapshot failed: %s", exc)
            return None

    def earned_badges(self, student_id: str) -> list:
        """All badges earned by the student."""
        if not self.available:
            return []
        try:
            return self._engine.earned_badges(student_id)   # type: ignore[union-attr]
        except Exception as exc:
            log.warning("EngagementService.earned_badges failed: %s", exc)
            return []

    def earned_since(self, student_id: str, since: str) -> list:
        """Badges earned after a given ISO timestamp."""
        if not self.available:
            return []
        try:
            return self._engine.earned_since(student_id, since)  # type: ignore[union-attr]
        except Exception as exc:
            log.warning("EngagementService.earned_since failed: %s", exc)
            return []
