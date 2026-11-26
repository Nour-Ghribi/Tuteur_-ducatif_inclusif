"""BadgeEngine: evaluates badge rules against the ledger and awards new badges.

Badges are defined in badges.yaml (declarative). The engine loads them once
and evaluates every unearthed badge after each session. It writes new
BadgeEvents to the DB and returns the list of newly earned badges so the
service layer can include them in the session response.

Design:
- Idempotent: re-running on the same data never duplicates badges.
- Additive: existing badges are never revoked.
- Transparent: every award includes the trigger value that crossed the threshold.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import yaml

from tuteur.adaptive.database import SQLiteRepository

from .models import BadgeDefinition, BadgeEvent, EngagementSnapshot

_BADGES_PATH = Path(__file__).parent / "badges.yaml"


@lru_cache(maxsize=1)
def _load_definitions() -> list[BadgeDefinition]:
    raw = yaml.safe_load(_BADGES_PATH.read_text(encoding="utf-8"))
    return [BadgeDefinition(**b) for b in raw["badges"]]


class BadgeEngine:
    """Evaluates badge triggers and writes new BadgeEvents to the DB."""

    def __init__(self, repository: SQLiteRepository) -> None:
        self._repo = repository

    def evaluate_after_session(
        self,
        student_id: str,
        snapshot: EngagementSnapshot,
    ) -> list[BadgeEvent]:
        """Evaluate all badge definitions; return newly awarded ones.

        Called after EngagementComputer.compute() so the snapshot is fresh.
        """
        already_earned = self._earned_badge_ids(student_id)
        ledger = self._ledger_metrics(student_id, snapshot)
        new_badges: list[BadgeEvent] = []

        for defn in _load_definitions():
            if defn.id in already_earned:
                continue
            earned, context = self._check(defn, ledger, student_id)
            if earned:
                event = BadgeEvent(
                    id=f"badge-{uuid.uuid4().hex[:12]}",
                    student_id=student_id,
                    badge_id=defn.id,
                    tier=defn.tier,
                    earned_at=datetime.now(UTC),
                    context=context,
                )
                self._save(event)
                new_badges.append(event)

        return new_badges

    def earned_badges(self, student_id: str) -> list[BadgeEvent]:
        """All badges earned by a student, most recent first."""
        rows = self._repo.fetchall(
            """SELECT * FROM badge_events
               WHERE student_id = ?
               ORDER BY earned_at DESC""",
            (student_id,),
        )
        return [self._row_to_event(r) for r in rows]

    def earned_since(self, student_id: str, since: str) -> list[BadgeEvent]:
        """Badges earned after a given ISO timestamp (for period reports)."""
        rows = self._repo.fetchall(
            """SELECT * FROM badge_events
               WHERE student_id = ? AND earned_at >= ?
               ORDER BY earned_at DESC""",
            (student_id, since),
        )
        return [self._row_to_event(r) for r in rows]

    # ------------------------------------------------------------------
    # Trigger evaluation
    # ------------------------------------------------------------------

    def _check(
        self,
        defn: BadgeDefinition,
        ledger: dict,
        student_id: str,
    ) -> tuple[bool, dict]:
        """Returns (earned, context_dict)."""
        metric = defn.trigger_metric
        value = defn.trigger_value

        if defn.trigger_type == "first_time":
            current = ledger.get(metric, 0)
            earned = current >= 1
            return earned, {"metric": metric, "value": current}

        if defn.trigger_type == "threshold":
            current = ledger.get(metric, 0.0)
            earned = current >= value
            return earned, {"metric": metric, "value": current, "threshold": value}

        if defn.trigger_type == "streak":
            streak = ledger.get("current_streak_days", 0)
            earned = streak >= value
            return earned, {"streak_days": streak, "threshold": value}

        if defn.trigger_type == "skill_accuracy":
            # Check if ANY skill meets the threshold with enough attempts
            skill_rows = self._repo.fetchall(
                """SELECT q.skill_id,
                          COUNT(*) as n,
                          AVG(CAST(a.is_correct AS REAL)) as acc
                   FROM attempts a
                   JOIN questions q ON q.id = a.question_id
                   WHERE a.student_id = ? AND a.submitted_at IS NOT NULL
                     AND a.is_correct IS NOT NULL
                   GROUP BY q.skill_id
                   HAVING n >= ? AND acc >= ?""",
                (student_id, defn.trigger_min_attempts, value),
            )
            if skill_rows:
                best = max(skill_rows, key=lambda r: r["acc"])
                return True, {
                    "skill_id": best["skill_id"],
                    "accuracy": round(best["acc"], 3),
                    "attempts": best["n"],
                }
            return False, {}

        return False, {}

    # ------------------------------------------------------------------
    # Ledger metrics dict (what badges can reference)
    # ------------------------------------------------------------------

    def _ledger_metrics(
        self, student_id: str, snapshot: EngagementSnapshot
    ) -> dict:
        """Flat dict of all numeric metrics a badge trigger can reference."""
        # Basic counts
        counts = self._repo.fetchone(
            """SELECT COUNT(*) as attempts_total,
                      COUNT(DISTINCT session_id) as sessions_total,
                      COUNT(DISTINCT DATE(submitted_at)) as active_days
               FROM attempts
               WHERE student_id = ? AND submitted_at IS NOT NULL""",
            (student_id,),
        )
        attempts_total = counts["attempts_total"] if counts else 0
        active_days = counts["active_days"] if counts else 0

        # Current streak (consecutive days up to today)
        day_rows = self._repo.fetchall(
            """SELECT DISTINCT DATE(submitted_at) as day
               FROM attempts
               WHERE student_id = ? AND submitted_at IS NOT NULL
               ORDER BY day DESC""",
            (student_id,),
        )
        streak = self._compute_streak([r["day"] for r in day_rows])

        # Recovery rate
        rec_rows = self._repo.fetchall(
            """SELECT o.recovered
               FROM recovery_outcomes o
               JOIN remediation_recommendations r ON r.id = o.recommendation_id
               WHERE r.student_id = ? AND o.status = 'observed'""",
            (student_id,),
        )
        recovery_rate = (
            sum(int(r["recovered"]) for r in rec_rows) / len(rec_rows)
            if rec_rows else 0.0
        )

        return {
            "attempts_total": attempts_total,
            "sessions_total": counts["sessions_total"] if counts else 0,
            "active_days": active_days,
            "current_streak_days": streak,
            "recovery_rate": recovery_rate,
            # Engagement scores from the snapshot
            "curiosity_score": snapshot.curiosity_score,
            "persistence_score": snapshot.persistence_score,
            "autonomy_score": snapshot.autonomy_score,
        }

    @staticmethod
    def _compute_streak(days_desc: list[str]) -> int:
        """Counts consecutive days ending today (or yesterday)."""
        if not days_desc:
            return 0
        from datetime import date, timedelta
        today = date.today()
        streak = 0
        expected = today
        for day_str in days_desc:
            d = date.fromisoformat(day_str)
            if d == expected or d == expected - timedelta(days=1) and streak == 0:
                streak += 1
                expected = d - timedelta(days=1)
            elif d < expected:
                break
        return streak

    # ------------------------------------------------------------------
    # DB persistence
    # ------------------------------------------------------------------

    def _earned_badge_ids(self, student_id: str) -> set[str]:
        rows = self._repo.fetchall(
            "SELECT badge_id FROM badge_events WHERE student_id = ?",
            (student_id,),
        )
        return {r["badge_id"] for r in rows}

    def _save(self, event: BadgeEvent) -> None:
        import json
        self._repo.fetchone(  # reuse the connection helper for the write
            # We use fetchone here as a passthrough; actual write below
            "SELECT 1",
        )
        # Direct write (SQLiteRepository doesn't have a generic execute,
        # so we use its internal connection helper via a small shim)
        with self._repo.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO badge_events
                   (id, student_id, badge_id, tier, earned_at, context_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event.id,
                    event.student_id,
                    event.badge_id,
                    event.tier,
                    event.earned_at.isoformat(),
                    json.dumps(event.context, ensure_ascii=False),
                ),
            )

    @staticmethod
    def _row_to_event(row) -> BadgeEvent:
        import json
        return BadgeEvent(
            id=row["id"],
            student_id=row["student_id"],
            badge_id=row["badge_id"],
            tier=row["tier"],
            earned_at=datetime.fromisoformat(row["earned_at"]),
            context=json.loads(row["context_json"] or "{}"),
        )
