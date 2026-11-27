"""ParentReportService — builds and stores parent/supervisor progress reports.

This service:
1. Loads ledger aggregates for a single student + period.
2. Loads the latest engagement snapshot (curiosity/persistence/autonomy).
3. Loads badges earned in the period.
4. Calls the GenAI LLM with the parent_report prompt to write a narrative.
5. Builds a TutorResponse with UISpec for display in the app.
6. Caches the generated report as a ReportRecord (for PDF export).

Privacy:
- Only aggregated metrics are passed to the LLM: attempt counts, success rates,
  skill labels, engagement tiers, badge labels.
- No raw answers, no session details, no timestamps of individual attempts.
- student_ref is pseudonymous; it is never passed to the LLM.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..schemas.common import Workflow
from ..schemas.responses import ResponseStatus, TutorResponse
from ..schemas.ui import (
    BadgeView,
    BadgeShelfBlock,
    CalloutBlock,
    MetricGridBlock,
    Metric,
    TextBlock,
    UISpec,
    UIMeta,
)


@dataclass
class ReportRecord:
    """Stored after generation so the PDF export can re-use it."""
    report_id: str
    student_ref: str
    period_start: str
    period_end: str
    language: str
    generated_at: datetime
    narrative: str                    # the LLM-generated text
    recurring_difficulties: list[str]
    metrics: dict                     # raw numbers for PDF table
    badges: list[dict]                # badge dicts for PDF


class ParentReportService:
    """Generates and stores parent progress reports.

    Parameters
    ----------
    ledger_path : Path | None
        Path to the student SQLite DB. If None, returns a 'no data' report.
    llm : Any
        The GenAI module's LLM instance (tuteur.llm.LLM).
        If None, the narrative is omitted and only metrics are shown.
    """

    def __init__(
        self,
        ledger_path: Path | None = None,
        llm=None,
    ) -> None:
        self._ledger_path = ledger_path
        self._llm = llm
        self._records: dict[str, ReportRecord] = {}   # in-memory cache for PDF export

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def generate(
        self,
        student_ref: str,
        period_start: str,
        period_end: str,
        language: str = "fr",
    ) -> TutorResponse:
        """Generate a parent report and return it as a TutorResponse."""
        request_id = uuid.uuid4().hex
        metrics = self._load_metrics(student_ref, period_start, period_end)
        eng = self._load_engagement(student_ref)
        badges = self._load_badges(student_ref, period_start)

        if not metrics:
            spec = UISpec(
                blocks=[CalloutBlock(tone="info", message_code="no_progress_yet")],
                meta=UIMeta(),
            )
            return TutorResponse(
                request_id=request_id,
                workflow=Workflow.PARENT_REPORT,
                intent=Workflow.PARENT_REPORT.value,
                status=ResponseStatus.OK,
                ui=spec,
            )

        narrative, difficulties = self._generate_narrative(
            metrics, eng, badges, language, period_start, period_end
        )

        # Store for PDF export
        record = ReportRecord(
            report_id=request_id,
            student_ref=student_ref,
            period_start=period_start,
            period_end=period_end,
            language=language,
            generated_at=datetime.now(UTC),
            narrative=narrative,
            recurring_difficulties=difficulties,
            metrics=metrics,
            badges=badges,
        )
        self._records[request_id] = record

        blocks = self._build_blocks(narrative, difficulties, metrics, badges)
        spec = UISpec(
            blocks=blocks,
            meta=UIMeta(language=language),
        )
        return TutorResponse(
            request_id=request_id,
            workflow=Workflow.PARENT_REPORT,
            intent=Workflow.PARENT_REPORT.value,
            status=ResponseStatus.OK,
            ui=spec,
        )

    def get_record(self, report_id: str) -> ReportRecord | None:
        return self._records.get(report_id)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_metrics(
        self, student_ref: str, period_start: str, period_end: str
    ) -> dict:
        if not self._ledger_path or not self._ledger_path.exists():
            return {}
        try:
            import sqlite3
            conn = sqlite3.connect(self._ledger_path)
            conn.row_factory = sqlite3.Row
            # Overall counts in period
            row = conn.execute(
                """SELECT
                     COUNT(*) as attempts,
                     COUNT(DISTINCT DATE(a.submitted_at)) as active_days,
                     AVG(CAST(a.is_correct AS REAL)) as success_rate
                   FROM attempts a
                   WHERE a.student_id = ?
                     AND a.submitted_at BETWEEN ? AND ?
                     AND a.is_correct IS NOT NULL""",
                (student_ref, period_start, period_end + "T23:59:59"),
            ).fetchone()

            if not row or row["attempts"] == 0:
                conn.close()
                return {}

            # Top skills (most attempted)
            top_rows = conn.execute(
                """SELECT s.display_label, COUNT(*) as n,
                          AVG(CAST(a.is_correct AS REAL)) as acc
                   FROM attempts a
                   JOIN questions q ON q.id = a.question_id
                   JOIN skills s ON s.id = q.skill_id
                   WHERE a.student_id = ?
                     AND a.submitted_at BETWEEN ? AND ?
                     AND a.is_correct IS NOT NULL
                   GROUP BY q.skill_id
                   ORDER BY n DESC
                   LIMIT 5""",
                (student_ref, period_start, period_end + "T23:59:59"),
            ).fetchall()

            top_skills = [r["display_label"] for r in top_rows]
            weak_skills = [
                r["display_label"] for r in top_rows
                if r["acc"] is not None and r["acc"] < 0.6
            ]
            conn.close()

            return {
                "attempts_total": int(row["attempts"]),
                "active_days": int(row["active_days"]),
                "success_rate": round(float(row["success_rate"] or 0) * 100, 1),
                "top_skills": top_skills,
                "weak_skills": weak_skills,
            }
        except Exception:
            return {}

    def _load_engagement(self, student_ref: str) -> dict:
        if not self._ledger_path or not self._ledger_path.exists():
            return {}
        try:
            import sqlite3
            conn = sqlite3.connect(self._ledger_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT curiosity_score, persistence_score, autonomy_score
                   FROM engagement_snapshots
                   WHERE student_id = ?
                   ORDER BY computed_at DESC LIMIT 1""",
                (student_ref,),
            ).fetchone()
            conn.close()
            if not row:
                return {}
            def tier(s: float) -> str:
                return "high" if s >= 0.7 else ("medium" if s >= 0.3 else "low")
            return {
                "curiosity_tier": tier(row["curiosity_score"]),
                "persistence_tier": tier(row["persistence_score"]),
                "autonomy_tier": tier(row["autonomy_score"]),
            }
        except Exception:
            return {}

    def _load_badges(self, student_ref: str, since: str) -> list[dict]:
        if not self._ledger_path or not self._ledger_path.exists():
            return []
        try:
            import sqlite3
            conn = sqlite3.connect(self._ledger_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT badge_id, tier, earned_at FROM badge_events
                   WHERE student_id = ? AND earned_at >= ?
                   ORDER BY earned_at DESC""",
                (student_ref, since),
            ).fetchall()
            conn.close()
            return [{"badge_id": r["badge_id"], "tier": r["tier"], "earned_at": r["earned_at"]} for r in rows]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # LLM narrative generation
    # ------------------------------------------------------------------

    def _generate_narrative(
        self,
        metrics: dict,
        eng: dict,
        badges: list[dict],
        language: str,
        period_start: str,
        period_end: str,
    ) -> tuple[str, list[str]]:
        if self._llm is None:
            return "", []
        try:
            from ..genai_ext.loader import load_ext_prompt
            from ..schemas.content import ReportSummaryContent

            prompt = load_ext_prompt("parent_report")
            badge_labels = ", ".join(b["badge_id"].replace("_", " ") for b in badges[:5]) or "aucun"
            top = ", ".join(metrics.get("top_skills", [])) or "—"
            weak = ", ".join(metrics.get("weak_skills", [])) or "aucune"

            system, user = prompt.render(
                language=language,
                school_level="middle",   # neutral tone for parent reports
                period=f"{period_start} → {period_end}",
                active_days=str(metrics.get("active_days", 0)),
                attempts_total=str(metrics.get("attempts_total", 0)),
                success_rate=str(metrics.get("success_rate", 0)),
                top_skills=top,
                weak_skills=weak,
                curiosity_tier=eng.get("curiosity_tier", "—"),
                persistence_tier=eng.get("persistence_tier", "—"),
                badges=badge_labels,
            )
            result = self._llm.structured(system, user, ReportSummaryContent)
            return result.summary, result.recurring_difficulties
        except Exception:
            return "", []

    # ------------------------------------------------------------------
    # UI block assembly
    # ------------------------------------------------------------------

    def _build_blocks(
        self,
        narrative: str,
        difficulties: list[str],
        metrics: dict,
        badges: list[dict],
    ) -> list:
        blocks: list = []

        # Metric summary
        metric_items = [
            Metric(label_code="attempts", value=metrics.get("attempts_total", 0), unit="count"),
            Metric(label_code="active_days", value=metrics.get("active_days", 0), unit="count"),
            Metric(label_code="success_rate", value=metrics.get("success_rate", 0) / 100, unit="ratio"),
        ]
        blocks.append(MetricGridBlock(metrics=metric_items))

        # LLM narrative
        if narrative:
            blocks.append(TextBlock(text=narrative[:4000]))

        # Recent badges
        if badges:
            try:
                from tuteur.adaptive.engagement.badge_engine import _load_definitions
                defs = {d.id: d for d in _load_definitions()}
            except Exception:
                defs = {}
            badge_views = []
            for b in badges[:10]:
                defn = defs.get(b["badge_id"])
                label = defn.label_fr if defn else b["badge_id"].replace("_", " ")
                icon = defn.icon if defn else "star"
                badge_views.append(BadgeView(
                    badge_id=b["badge_id"],
                    label=label[:120],
                    icon=icon[:60],
                    tier=b["tier"],
                    earned_at=b["earned_at"][:10] if b["earned_at"] else None,
                ))
            if badge_views:
                blocks.append(BadgeShelfBlock(badges=badge_views))

        return blocks
