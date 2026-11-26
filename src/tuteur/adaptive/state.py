from __future__ import annotations

from datetime import datetime

import numpy as np

from tuteur.adaptive.database import SQLiteRepository
from tuteur.adaptive.models import StudentState
from tuteur.schemas import QuizItem

DIFFICULTY_VALUE = {"facile": 0.0, "moyen": 0.5, "difficile": 1.0}


class StudentStateBuilder:
    """Build the versioned decision-time state from persisted platform interactions only."""

    def __init__(self, repository: SQLiteRepository):
        self.repository = repository

    def build(self, current_attempt_id: str) -> StudentState:
        current = self.repository.fetchone(
            """SELECT a.*,q.skill_id,q.payload_json FROM attempts a
            JOIN questions q ON q.id=a.question_id WHERE a.id=?""",
            (current_attempt_id,),
        )
        if current is None:
            raise KeyError(current_attempt_id)
        if current["submitted_at"] is None or current["is_correct"] is None:
            raise ValueError("current attempt must have a deterministically graded submission")
        if bool(current["is_correct"]):
            raise ValueError("remediation state requires a current incorrect attempt")

        student_id = str(current["student_id"])
        skill_id = str(current["skill_id"])
        decision_time = datetime.fromisoformat(current["submitted_at"])
        all_rows = self.repository.fetchall(
            """SELECT a.*,q.skill_id FROM attempts a JOIN questions q ON q.id=a.question_id
            WHERE a.student_id=? AND a.submitted_at IS NOT NULL
            ORDER BY a.submitted_at,a.seq""",
            (student_id,),
        )
        boundary = (str(current["submitted_at"]), int(current["seq"]))
        available = [
            row for row in all_rows
            if (str(row["submitted_at"]), int(row["seq"])) <= boundary
        ]
        positions = [i for i, row in enumerate(available) if row["id"] == current_attempt_id]
        if positions != [len(available) - 1]:
            raise ValueError("current attempt is not the final event at its deterministic boundary")
        prior = available[:-1]
        prior_skill = [row for row in prior if row["skill_id"] == skill_id]
        including_current = available[-5:]
        recent_accuracy = float(np.mean([int(row["is_correct"]) for row in including_current]))

        consecutive = 0
        for row in reversed(available):
            if bool(row["is_correct"]):
                break
            consecutive += 1

        trend = None
        if len(available) >= 6:
            latest = [int(row["is_correct"]) for row in available[-3:]]
            previous = [int(row["is_correct"]) for row in available[-6:-3]]
            trend = float(np.mean(latest) - np.mean(previous))

        response_time = self._elapsed_seconds(current["presented_at"], current["submitted_at"])
        since_previous = None
        if prior:
            since_previous = self._elapsed_seconds(prior[-1]["submitted_at"], current["submitted_at"])

        item = QuizItem.model_validate_json(current["payload_json"])
        difficulty = DIFFICULTY_VALUE.get(item.difficulty)
        decision_iso = current["submitted_at"]
        displayed = self.repository.fetchall(
            """SELECT r.skill_id FROM remediation_events e
            JOIN remediation_recommendations r ON r.id=e.recommendation_id
            WHERE r.student_id=? AND e.event_type='displayed' AND e.event_time < ?
            ORDER BY e.event_time,e.seq""",
            (student_id, decision_iso),
        )
        recoveries = self.repository.fetchall(
            """SELECT o.recovered FROM recovery_outcomes o
            JOIN remediation_recommendations r ON r.id=o.recommendation_id
            WHERE r.student_id=? AND o.status='observed' AND o.observed_at < ?
            ORDER BY o.observed_at,o.id""",
            (student_id, decision_iso),
        )
        recovery_rate = (
            float(np.mean([int(row["recovered"]) for row in recoveries]))
            if recoveries else None
        )
        skill_accuracy = (
            float(np.mean([int(row["is_correct"]) for row in prior_skill]))
            if prior_skill else None
        )
        return StudentState(
            student_id=student_id,
            skill_id=skill_id,
            current_attempt_id=current_attempt_id,
            decision_time=decision_time,
            prior_answer_count=len(prior),
            recent_accuracy_5_including_current=recent_accuracy,
            skill_attempt_count_prior=len(prior_skill),
            skill_accuracy_prior=skill_accuracy,
            consecutive_failures_including_current=consecutive,
            recent_performance_trend_3v3=trend,
            current_response_time_s=response_time,
            time_since_previous_answer_s=since_previous,
            authored_question_difficulty=difficulty,
            prior_displayed_remediation_count=len(displayed),
            prior_displayed_skill_remediation_count=sum(
                row["skill_id"] == skill_id for row in displayed
            ),
            prior_observed_recovery_rate=recovery_rate,
            student_cold_start=not prior,
            skill_cold_start=not prior_skill,
        )

    @staticmethod
    def _elapsed_seconds(start: str | None, end: str | None) -> float | None:
        if not start or not end:
            return None
        seconds = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
        return max(0.0, float(seconds))
