"""Profile storage: protocol + two implementations.

InMemoryProfileStore  — development / single-process (default)
SQLiteProfileStore    — persistent, file-backed, production-safe

Both are thread-safe for reads; writes use a simple lock.
The SQLite implementation stores the full profile as a JSON blob alongside
indexed columns for fast lookup by subject_ref.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import OrderedDict
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Protocol

from .models import StudentProfile


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class ProfileStore(Protocol):
    def get(self, subject_ref: str) -> StudentProfile | None: ...
    def save(self, profile: StudentProfile) -> None: ...
    def delete(self, subject_ref: str) -> None: ...


# ---------------------------------------------------------------------------
# In-memory (dev / test)
# ---------------------------------------------------------------------------

class InMemoryProfileStore:
    def __init__(self, max_entries: int = 10_000) -> None:
        self._data: OrderedDict[str, StudentProfile] = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()

    def get(self, subject_ref: str) -> StudentProfile | None:
        with self._lock:
            return self._data.get(subject_ref)

    def save(self, profile: StudentProfile) -> None:
        with self._lock:
            self._data[subject_ref := profile.subject_ref] = profile
            self._data.move_to_end(subject_ref)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def delete(self, subject_ref: str) -> None:
        with self._lock:
            self._data.pop(subject_ref, None)


# ---------------------------------------------------------------------------
# SQLite (persistent)
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS student_profiles (
    subject_ref     TEXT PRIMARY KEY,
    age_group       TEXT NOT NULL,
    school_level    TEXT NOT NULL,
    cognitive_need  TEXT NOT NULL DEFAULT 'none',
    vision_need     TEXT NOT NULL DEFAULT 'none',
    hearing_need    TEXT NOT NULL DEFAULT 'none',
    motor_need      TEXT NOT NULL DEFAULT 'none',
    language_pref   TEXT NOT NULL DEFAULT 'fr',
    prefs_json      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""


class SQLiteProfileStore:
    """Persistent profile store backed by SQLite.

    Uses the same database file as the RL adaptive system so the
    profile and interaction history share one connection path.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get(self, subject_ref: str) -> StudentProfile | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM student_profiles WHERE subject_ref = ?",
                (subject_ref,),
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def save(self, profile: StudentProfile) -> None:
        now = datetime.now(UTC).isoformat()
        prefs_json = profile.rendering_preferences.model_dump_json()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO student_profiles
                    (subject_ref, age_group, school_level, cognitive_need,
                     vision_need, hearing_need, motor_need, language_pref,
                     prefs_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject_ref) DO UPDATE SET
                    age_group      = excluded.age_group,
                    school_level   = excluded.school_level,
                    cognitive_need = excluded.cognitive_need,
                    vision_need    = excluded.vision_need,
                    hearing_need   = excluded.hearing_need,
                    motor_need     = excluded.motor_need,
                    language_pref  = excluded.language_pref,
                    prefs_json     = excluded.prefs_json,
                    updated_at     = excluded.updated_at
                """,
                (
                    profile.subject_ref,
                    profile.age_group.value,
                    profile.school_level.value,
                    profile.cognitive_need.value,
                    profile.vision_need.value,
                    profile.hearing_need.value,
                    profile.motor_need.value,
                    profile.language_preference,
                    prefs_json,
                    profile.created_at.isoformat(),
                    now,
                ),
            )

    def delete(self, subject_ref: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM student_profiles WHERE subject_ref = ?",
                (subject_ref,),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StudentProfile:
        from .models import (
            AgeGroup, CognitiveNeed, HearingNeed,
            MotorNeed, RenderingPreferences, SchoolLevel, VisionNeed,
        )
        prefs = RenderingPreferences.model_validate_json(row["prefs_json"])
        return StudentProfile(
            subject_ref=row["subject_ref"],
            age_group=AgeGroup(row["age_group"]),
            school_level=SchoolLevel(row["school_level"]),
            cognitive_need=CognitiveNeed(row["cognitive_need"]),
            vision_need=VisionNeed(row["vision_need"]),
            hearing_need=HearingNeed(row["hearing_need"]),
            motor_need=MotorNeed(row["motor_need"]),
            language_preference=row["language_pref"],
            rendering_preferences=prefs,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
