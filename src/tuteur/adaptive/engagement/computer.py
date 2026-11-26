"""EngagementComputer: derives curiosity, persistence and autonomy scores
from raw ledger data.

All three scores are floats in [0, 1] computed from the student's full
interaction history in the SQLite ledger. They are computed after each
session ends (called by the session-close path in the service layer).

Formulas are intentionally transparent and simple:
- No black-box models.
- Every formula is documented here and can be tuned by changing the
  weights dict at the top of each method.
- Scores are clipped to [0, 1] before storage.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime

from tuteur.adaptive.database import SQLiteRepository

from .models import EngagementSnapshot


class EngagementComputer:
    """Computes engagement scores from the SQLite ledger for one student."""

    def __init__(self, repository: SQLiteRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def compute(self, student_id: str) -> EngagementSnapshot:
        """Compute a fresh EngagementSnapshot for the given student.

        Returns a snapshot with all-zero scores if the student has no
        history yet (graceful cold-start).
        """
        attempts = self._all_attempts(student_id)
        sessions = self._all_sessions(student_id)

        if not attempts:
            return EngagementSnapshot(
                student_id=student_id,
                sessions_used=0,
                attempts_used=0,
            )

        curiosity = self._curiosity(student_id, attempts, sessions)
        persistence = self._persistence(student_id, attempts)
        autonomy = self._autonomy(student_id, sessions)

        return EngagementSnapshot(
            student_id=student_id,
            curiosity_score=round(max(0.0, min(1.0, curiosity)), 4),
            persistence_score=round(max(0.0, min(1.0, persistence)), 4),
            autonomy_score=round(max(0.0, min(1.0, autonomy)), 4),
            sessions_used=len(sessions),
            attempts_used=len(attempts),
        )

    # ------------------------------------------------------------------
    # Curiosity
    # ------------------------------------------------------------------

    def _curiosity(self, student_id: str, attempts: list, sessions: list) -> float:
        """How much does the student explore beyond required tasks?

        Signals (each contributes a component to a weighted sum):
        1. explanation_ratio  — proportion of activities that were explanations
                                or exploratory formats (concept_map, concept_cards)
                                vs. quiz/exercise. High = more curious.
        2. topic_breadth      — number of distinct skills/topics touched per session.
                                Normalised by log to avoid penalising long sessions.
        3. revisit_rate       — proportion of sessions where the student came back
                                to a topic they already visited. Moderate = healthy curiosity.
        """
        w = {"explanation_ratio": 0.45, "topic_breadth": 0.40, "revisit_rate": 0.15}

        # 1. explanation ratio: count questions whose skill label suggests
        #    an explanatory intent (we use prompt_tag as a proxy).
        explanation_count = sum(
            1 for a in attempts
            if self._is_exploratory(a)
        )
        explanation_ratio = explanation_count / len(attempts)

        # 2. topic breadth per session
        breadths: list[float] = []
        for session in sessions:
            skills_in_session = {
                a["skill_id"] for a in attempts
                if a["session_id"] == session["id"]
            }
            breadths.append(math.log1p(len(skills_in_session)))
        avg_breadth = sum(breadths) / len(breadths) if breadths else 0.0
        # Normalise: log1p(5 topics) ≈ 1.79 → score ≈ 1.0 at 5 topics per session
        breadth_score = min(avg_breadth / math.log1p(5), 1.0)

        # 3. revisit rate
        all_skills: list[str] = []
        revisit_count = 0
        for session in sessions:
            session_skills = {
                a["skill_id"] for a in attempts
                if a["session_id"] == session["id"]
            }
            if session_skills & set(all_skills):
                revisit_count += 1
            all_skills.extend(session_skills)
        revisit_rate = revisit_count / len(sessions) if sessions else 0.0
        # Moderate revisit (0.3-0.6) is healthy; too high means stuck
        revisit_score = 1.0 - abs(revisit_rate - 0.4) / 0.6

        return (
            w["explanation_ratio"] * explanation_ratio
            + w["topic_breadth"] * breadth_score
            + w["revisit_rate"] * max(0.0, revisit_score)
        )

    @staticmethod
    def _is_exploratory(attempt: dict) -> bool:
        """Heuristic: prompt_tag contains 'answer', 'explanation', or 'concept'."""
        tag = (attempt.get("prompt_tag") or "").lower()
        return any(k in tag for k in ("answer", "explanation", "concept", "step", "comparison"))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persistence(self, student_id: str, attempts: list) -> float:
        """How much does the student keep trying after failure?

        Signals:
        1. recovery_rate  — proportion of incorrect attempts followed by a
                            correct attempt on the same skill. Already stored
                            in recovery_outcomes; fall back to computing inline.
        2. retry_ratio    — proportion of failed attempts where the student
                            attempted the same skill again (at least once more).
        3. remediation_completion — proportion of displayed remediations that
                            were completed (event_type='completed').
        """
        w = {"recovery_rate": 0.50, "retry_ratio": 0.30, "remediation_completion": 0.20}

        # 1. Recovery rate from the DB
        recovery_rows = self._repo.fetchall(
            """SELECT o.recovered FROM recovery_outcomes o
               JOIN remediation_recommendations r ON r.id = o.recommendation_id
               WHERE r.student_id = ? AND o.status = 'observed'""",
            (student_id,),
        )
        recovery_rate = (
            sum(int(r["recovered"]) for r in recovery_rows) / len(recovery_rows)
            if recovery_rows else 0.5  # neutral prior for cold start
        )

        # 2. Retry ratio: for each incorrect attempt, did the student try again?
        incorrect = [a for a in attempts if a["is_correct"] == 0]
        if not incorrect:
            retry_ratio = 0.5  # no failures → neutral
        else:
            retried = 0
            skill_first_seen: dict[str, str] = {}  # skill_id -> submitted_at of first incorrect
            attempt_times = {a["id"]: a["submitted_at"] for a in attempts}
            for a in incorrect:
                skill = a["skill_id"]
                t = a["submitted_at"]
                # Did any later attempt on the same skill succeed?
                later_correct = any(
                    b["skill_id"] == skill
                    and b["is_correct"] == 1
                    and b["submitted_at"] > t
                    for b in attempts
                )
                if later_correct:
                    retried += 1
            retry_ratio = retried / len(incorrect)

        # 3. Remediation completion
        rem_rows = self._repo.fetchall(
            """SELECT event_type FROM remediation_events e
               JOIN remediation_recommendations r ON r.id = e.recommendation_id
               WHERE r.student_id = ? AND event_type IN ('displayed','completed')""",
            (student_id,),
        )
        displayed = sum(1 for r in rem_rows if r["event_type"] == "displayed")
        completed = sum(1 for r in rem_rows if r["event_type"] == "completed")
        rem_completion = completed / displayed if displayed > 0 else 0.5

        return (
            w["recovery_rate"] * recovery_rate
            + w["retry_ratio"] * retry_ratio
            + w["remediation_completion"] * rem_completion
        )

    # ------------------------------------------------------------------
    # Autonomy
    # ------------------------------------------------------------------

    def _autonomy(self, student_id: str, sessions: list) -> float:
        """How independently does the student navigate?

        Signals:
        1. session_frequency  — sessions per week (capped). More frequent
                                self-initiated sessions → higher autonomy.
        2. format_variety     — number of distinct prompt_tag prefixes used.
                                Students who explore formats on their own score higher.
        3. multi_session_rate — proportion of days with more than one session
                                (self-driven deep work).
        """
        w = {"session_frequency": 0.35, "format_variety": 0.40, "multi_session_rate": 0.25}

        if not sessions:
            return 0.0

        # 1. Session frequency per week
        dates = sorted({s["started_at"][:10] for s in sessions})
        if len(dates) >= 2:
            first = datetime.fromisoformat(dates[0]).replace(tzinfo=UTC)
            last = datetime.fromisoformat(dates[-1]).replace(tzinfo=UTC)
            weeks = max((last - first).days / 7, 1.0)
            sessions_per_week = len(sessions) / weeks
        else:
            sessions_per_week = 1.0
        # Normalise: 5 sessions/week → score 1.0
        freq_score = min(sessions_per_week / 5.0, 1.0)

        # 2. Format variety — distinct prompt_tag prefixes
        all_attempts = self._all_attempts(student_id)
        tags = {
            (a.get("prompt_tag") or "unknown").split("@")[0]
            for a in all_attempts
        }
        variety_score = min(len(tags) / 6.0, 1.0)  # 6 distinct formats → 1.0

        # 3. Multi-session rate (days with > 1 session)
        from collections import Counter
        sessions_per_day = Counter(s["started_at"][:10] for s in sessions)
        multi_days = sum(1 for v in sessions_per_day.values() if v > 1)
        multi_rate = multi_days / len(sessions_per_day) if sessions_per_day else 0.0

        return (
            w["session_frequency"] * freq_score
            + w["format_variety"] * variety_score
            + w["multi_session_rate"] * multi_rate
        )

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _all_attempts(self, student_id: str) -> list[dict]:
        rows = self._repo.fetchall(
            """SELECT a.id, a.session_id, a.submitted_at, a.is_correct,
                      a.presented_at, q.skill_id, q.prompt_tag
               FROM attempts a
               JOIN questions q ON q.id = a.question_id
               WHERE a.student_id = ? AND a.submitted_at IS NOT NULL
               ORDER BY a.submitted_at""",
            (student_id,),
        )
        return [dict(r) for r in rows]

    def _all_sessions(self, student_id: str) -> list[dict]:
        rows = self._repo.fetchall(
            "SELECT * FROM quiz_sessions WHERE student_id = ? ORDER BY started_at",
            (student_id,),
        )
        return [dict(r) for r in rows]
