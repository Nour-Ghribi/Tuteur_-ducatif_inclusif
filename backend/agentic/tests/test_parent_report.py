"""Tests for the ParentReportService."""
from __future__ import annotations

import pytest

from tutor_agentic.reporting.parent import ParentReportService
from tutor_agentic.schemas.common import Workflow
from tutor_agentic.schemas.responses import ResponseStatus


# ---------------------------------------------------------------------------
# No-data case (no ledger)
# ---------------------------------------------------------------------------

def test_no_ledger_returns_no_progress_callout():
    svc = ParentReportService(ledger_path=None, llm=None)
    response = svc.generate(
        student_ref="s1",
        period_start="2026-01-01",
        period_end="2026-12-31",
        language="fr",
    )
    assert response.workflow == Workflow.PARENT_REPORT
    assert response.status == ResponseStatus.OK
    # With no data, should contain a no_progress_yet callout
    block_types = [b.type for b in response.ui.blocks]
    assert "callout" in block_types


def test_no_ledger_no_llm_does_not_raise():
    """Service must not raise even with nothing configured."""
    svc = ParentReportService(ledger_path=None, llm=None)
    response = svc.generate("s-nobody", "2026-01-01", "2026-06-30", "ar")
    assert response is not None


def test_report_has_request_id():
    svc = ParentReportService(ledger_path=None, llm=None)
    response = svc.generate("s1", "2026-01-01", "2026-12-31", "en")
    assert len(response.request_id) > 0


def test_get_record_before_generation_returns_none():
    svc = ParentReportService(ledger_path=None, llm=None)
    assert svc.get_record("nonexistent-id") is None


def test_get_record_after_generation_returns_record():
    svc = ParentReportService(ledger_path=None, llm=None)
    response = svc.generate("s1", "2026-01-01", "2026-12-31", "fr")
    # Even with no-data, a record is stored
    record = svc.get_record(response.request_id)
    assert record is not None
    assert record.student_ref == "s1"
    assert record.language == "fr"


def test_report_language_stored_in_record():
    svc = ParentReportService(ledger_path=None, llm=None)
    response = svc.generate("s2", "2026-01-01", "2026-06-30", "ar")
    record = svc.get_record(response.request_id)
    assert record.language == "ar"


def test_different_students_get_different_records():
    svc = ParentReportService(ledger_path=None, llm=None)
    r1 = svc.generate("s1", "2026-01-01", "2026-06-30", "fr")
    r2 = svc.generate("s2", "2026-01-01", "2026-06-30", "fr")
    assert r1.request_id != r2.request_id
    assert svc.get_record(r1.request_id).student_ref == "s1"
    assert svc.get_record(r2.request_id).student_ref == "s2"
