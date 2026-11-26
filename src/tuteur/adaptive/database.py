from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from tuteur.adaptive.models import RemediationDecision, StudentState, stable_skill_id
from tuteur.schemas import QuizItem


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS students (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS courses (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
  id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id), canonical_label TEXT NOT NULL,
  display_label TEXT NOT NULL, UNIQUE(course_id, canonical_label)
);
CREATE TABLE IF NOT EXISTS quiz_sessions (
  id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id),
  course_id TEXT NOT NULL REFERENCES courses(id), reading_level TEXT NOT NULL,
  started_at TEXT NOT NULL, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS questions (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES quiz_sessions(id),
  course_id TEXT NOT NULL REFERENCES courses(id), skill_id TEXT NOT NULL REFERENCES skills(id),
  parent_question_id TEXT REFERENCES questions(id), is_followup INTEGER NOT NULL,
  payload_json TEXT NOT NULL, prompt_tag TEXT, model_version TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
  question_id TEXT NOT NULL REFERENCES questions(id), session_id TEXT NOT NULL REFERENCES quiz_sessions(id),
  student_id TEXT NOT NULL REFERENCES students(id), presented_at TEXT NOT NULL,
  submitted_at TEXT, submitted_answer TEXT, is_correct INTEGER,
  grading_method TEXT, attempt_number INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS remediation_recommendations (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL REFERENCES quiz_sessions(id), student_id TEXT NOT NULL REFERENCES students(id),
  skill_id TEXT NOT NULL REFERENCES skills(id), failed_attempt_id TEXT NOT NULL REFERENCES attempts(id),
  state_json TEXT NOT NULL, vector_json TEXT NOT NULL, state_hash TEXT NOT NULL,
  state_schema_version TEXT NOT NULL, vector_schema_version TEXT NOT NULL,
  strategy_id TEXT NOT NULL, policy_type TEXT NOT NULL, policy_version TEXT NOT NULL,
  provenance TEXT NOT NULL, reason TEXT NOT NULL, assignment_mechanism TEXT NOT NULL,
  action_probability REAL, decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS remediation_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
  recommendation_id TEXT NOT NULL REFERENCES remediation_recommendations(id),
  event_type TEXT NOT NULL CHECK(event_type IN ('generated','displayed','viewed','completed')),
  strategy_id TEXT NOT NULL, payload_json TEXT, event_time TEXT NOT NULL,
  UNIQUE(recommendation_id, event_type)
);
CREATE TABLE IF NOT EXISTS recovery_outcomes (
  id TEXT PRIMARY KEY, recommendation_id TEXT NOT NULL UNIQUE REFERENCES remediation_recommendations(id),
  followup_attempt_id TEXT REFERENCES attempts(id), status TEXT NOT NULL CHECK(status IN ('pending','observed','censored')),
  recovered INTEGER, observed_at TEXT, censor_reason TEXT,
  CHECK((status='observed' AND recovered IS NOT NULL AND observed_at IS NOT NULL) OR status!='observed')
);
CREATE TABLE IF NOT EXISTS engagement_snapshots (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id  TEXT NOT NULL REFERENCES students(id),
  computed_at TEXT NOT NULL,
  curiosity_score   REAL NOT NULL DEFAULT 0.0,
  persistence_score REAL NOT NULL DEFAULT 0.0,
  autonomy_score    REAL NOT NULL DEFAULT 0.0,
  sessions_used INTEGER NOT NULL DEFAULT 0,
  attempts_used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS badge_events (
  id          TEXT PRIMARY KEY,
  student_id  TEXT NOT NULL REFERENCES students(id),
  badge_id    TEXT NOT NULL,
  tier        TEXT NOT NULL DEFAULT 'bronze',
  earned_at   TEXT NOT NULL,
  context_json TEXT,
  UNIQUE(student_id, badge_id)
);
"""

# Applied once to existing DBs that pre-date these tables.
_MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS engagement_snapshots (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      student_id TEXT NOT NULL,
      computed_at TEXT NOT NULL,
      curiosity_score REAL NOT NULL DEFAULT 0.0,
      persistence_score REAL NOT NULL DEFAULT 0.0,
      autonomy_score REAL NOT NULL DEFAULT 0.0,
      sessions_used INTEGER NOT NULL DEFAULT 0,
      attempts_used INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS badge_events (
      id TEXT PRIMARY KEY,
      student_id TEXT NOT NULL,
      badge_id TEXT NOT NULL,
      tier TEXT NOT NULL DEFAULT 'bronze',
      earned_at TEXT NOT NULL,
      context_json TEXT,
      UNIQUE(student_id, badge_id)
    )""",
]


class SQLiteRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            # Apply additive migrations for DBs created before engagement tables
            for migration in _MIGRATIONS:
                try:
                    connection.execute(migration)
                except sqlite3.OperationalError:
                    pass  # table already exists — safe to skip

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_session(
        self, student_id: str, course_id: str, title: str, source: str,
        reading_level: str = "standard", session_id: str | None = None,
        at: datetime | None = None,
    ) -> str:
        at = at or utc_now()
        session_id = session_id or f"session-{uuid.uuid4().hex}"
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO students VALUES (?, ?)", (student_id, iso(at)))
            db.execute(
                "INSERT OR IGNORE INTO courses VALUES (?, ?, ?, ?)",
                (course_id, title, source, iso(at)),
            )
            db.execute(
                "INSERT OR IGNORE INTO quiz_sessions VALUES (?, ?, ?, ?, ?, NULL)",
                (session_id, student_id, course_id, reading_level, iso(at)),
            )
        return session_id

    def save_question(
        self, session_id: str, course_id: str, item: QuizItem, *,
        prompt_tag: str, model_version: str, parent_question_id: str | None = None,
        question_id: str | None = None, at: datetime | None = None,
    ) -> tuple[str, str]:
        from tuteur.adaptive.models import normalize_skill_label

        at = at or utc_now()
        question_id = question_id or f"question-{uuid.uuid4().hex}"
        skill_id = stable_skill_id(course_id, item.competence)
        canonical = normalize_skill_label(item.competence)
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO skills VALUES (?, ?, ?, ?)",
                (skill_id, course_id, canonical, item.competence),
            )
            db.execute(
                """INSERT OR IGNORE INTO questions
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    question_id, session_id, course_id, skill_id, parent_question_id,
                    int(parent_question_id is not None), item.model_dump_json(), prompt_tag,
                    model_version, iso(at),
                ),
            )
        return question_id, skill_id

    def present_question(
        self, question_id: str, session_id: str, student_id: str,
        at: datetime | None = None, attempt_id: str | None = None,
    ) -> str:
        at = at or utc_now()
        attempt_id = attempt_id or f"attempt-{uuid.uuid4().hex}"
        with self.connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO attempts
                (id, question_id, session_id, student_id, presented_at)
                VALUES (?, ?, ?, ?, ?)""",
                (attempt_id, question_id, session_id, student_id, iso(at)),
            )
        return attempt_id

    def submit_answer(
        self, attempt_id: str, answer: str, at: datetime | None = None
    ) -> bool | None:
        at = at or utc_now()
        with self.connect() as db:
            row = db.execute(
                """SELECT a.submitted_at, q.payload_json FROM attempts a
                JOIN questions q ON q.id=a.question_id WHERE a.id=?""",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise KeyError(attempt_id)
            if row["submitted_at"] is not None:
                existing = db.execute(
                    "SELECT submitted_answer, is_correct FROM attempts WHERE id=?", (attempt_id,)
                ).fetchone()
                if existing["submitted_answer"] != answer:
                    raise ValueError("attempt already submitted with a different answer")
                return None if existing["is_correct"] is None else bool(existing["is_correct"])
            item = QuizItem.model_validate_json(row["payload_json"])
            if item.type in {"qcm", "vrai_faux"}:
                correct = answer.strip() == item.answer.strip()
                method = "deterministic_choice_v1"
            else:
                correct = None
                method = "ungraded_free_text"
            db.execute(
                """UPDATE attempts SET submitted_at=?, submitted_answer=?, is_correct=?, grading_method=?
                WHERE id=?""",
                (iso(at), answer, None if correct is None else int(correct), method, attempt_id),
            )
        return correct

    def create_recommendation(
        self, session_id: str, failed_attempt_id: str, state: StudentState,
        decision: RemediationDecision, recommendation_id: str | None = None,
    ) -> str:
        recommendation_id = recommendation_id or f"recommendation-{uuid.uuid4().hex}"
        with self.connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO remediation_recommendations
                (id,session_id,student_id,skill_id,failed_attempt_id,state_json,vector_json,state_hash,
                 state_schema_version,vector_schema_version,strategy_id,policy_type,policy_version,
                 provenance,reason,assignment_mechanism,action_probability,decided_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    recommendation_id, session_id, state.student_id, state.skill_id,
                    failed_attempt_id, state.model_dump_json(), json.dumps(state.to_vector().tolist()),
                    state.snapshot_hash(), state.schema_version, state.vector_schema_version,
                    decision.strategy_id, decision.policy_type, decision.policy_version,
                    decision.provenance, decision.reason, decision.assignment_mechanism,
                    decision.action_probability, iso(decision.decided_at),
                ),
            )
        return recommendation_id

    def log_remediation_event(
        self, recommendation_id: str, event_type: str, strategy_id: str,
        payload: dict | None = None, at: datetime | None = None, event_id: str | None = None,
    ) -> str:
        at = at or utc_now()
        event_id = event_id or f"event-{uuid.uuid4().hex}"
        with self.connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO remediation_events
                (id,recommendation_id,event_type,strategy_id,payload_json,event_time)
                VALUES (?,?,?,?,?,?)""",
                (event_id, recommendation_id, event_type, strategy_id,
                 json.dumps(payload, ensure_ascii=False) if payload is not None else None, iso(at)),
            )
        return event_id

    def create_pending_recovery(
        self, recommendation_id: str, recovery_id: str | None = None
    ) -> str:
        recovery_id = recovery_id or f"recovery-{uuid.uuid4().hex}"
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO recovery_outcomes VALUES (?, ?, NULL, 'pending', NULL, NULL, NULL)",
                (recovery_id, recommendation_id),
            )
        return recovery_id

    def observe_recovery(
        self, recommendation_id: str, followup_attempt_id: str, at: datetime | None = None
    ) -> bool:
        at = at or utc_now()
        with self.connect() as db:
            attempt = db.execute(
                "SELECT is_correct, submitted_at FROM attempts WHERE id=?", (followup_attempt_id,)
            ).fetchone()
            if attempt is None or attempt["submitted_at"] is None or attempt["is_correct"] is None:
                raise ValueError("follow-up must have an observed deterministic outcome")
            recovered = bool(attempt["is_correct"])
            db.execute(
                """UPDATE recovery_outcomes SET followup_attempt_id=?,status='observed',
                recovered=?,observed_at=?,censor_reason=NULL WHERE recommendation_id=?""",
                (followup_attempt_id, int(recovered), iso(at), recommendation_id),
            )
        return recovered

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.connect() as db:
            return db.execute(sql, params).fetchall()

    # ------------------------------------------------------------------
    # Engagement snapshot persistence
    # ------------------------------------------------------------------

    def save_engagement_snapshot(self, snapshot: "EngagementSnapshot") -> None:  # type: ignore[name-defined]
        """Append a new engagement snapshot row (history is kept for trend charts)."""
        with self.connect() as db:
            db.execute(
                """INSERT INTO engagement_snapshots
                   (student_id, computed_at, curiosity_score, persistence_score,
                    autonomy_score, sessions_used, attempts_used)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot.student_id,
                    snapshot.computed_at.isoformat(),
                    snapshot.curiosity_score,
                    snapshot.persistence_score,
                    snapshot.autonomy_score,
                    snapshot.sessions_used,
                    snapshot.attempts_used,
                ),
            )

    def latest_engagement_snapshot(self, student_id: str):
        """Returns the most recent EngagementSnapshot row, or None."""
        row = self.fetchone(
            """SELECT * FROM engagement_snapshots
               WHERE student_id = ?
               ORDER BY computed_at DESC
               LIMIT 1""",
            (student_id,),
        )
        if row is None:
            return None
        from tuteur.adaptive.engagement.models import EngagementSnapshot
        from datetime import datetime
        return EngagementSnapshot(
            student_id=row["student_id"],
            computed_at=datetime.fromisoformat(row["computed_at"]),
            curiosity_score=row["curiosity_score"],
            persistence_score=row["persistence_score"],
            autonomy_score=row["autonomy_score"],
            sessions_used=row["sessions_used"],
            attempts_used=row["attempts_used"],
        )

    def engagement_history(self, student_id: str, limit: int = 30) -> list:
        """Returns the last N engagement snapshots for trend charts."""
        rows = self.fetchall(
            """SELECT * FROM engagement_snapshots
               WHERE student_id = ?
               ORDER BY computed_at DESC
               LIMIT ?""",
            (student_id, limit),
        )
        from tuteur.adaptive.engagement.models import EngagementSnapshot
        from datetime import datetime
        return [
            EngagementSnapshot(
                student_id=r["student_id"],
                computed_at=datetime.fromisoformat(r["computed_at"]),
                curiosity_score=r["curiosity_score"],
                persistence_score=r["persistence_score"],
                autonomy_score=r["autonomy_score"],
                sessions_used=r["sessions_used"],
                attempts_used=r["attempts_used"],
            )
            for r in rows
        ]

    def close_session(self, session_id: str, at: "datetime | None" = None) -> None:
        """Mark a session as ended. Called by the service after the last activity."""
        at = at or utc_now()
        with self.connect() as db:
            db.execute(
                "UPDATE quiz_sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
                (iso(at), session_id),
            )
