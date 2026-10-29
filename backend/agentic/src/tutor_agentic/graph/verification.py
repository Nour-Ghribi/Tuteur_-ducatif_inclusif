"""Critic checks run on generated content.

Each check reports its own id in ``VerificationReport.checks_run``, so the UI never implies that a
check ran when it did not. ``issues`` block the content (it is regenerated with the issue ids as
feedback, then abandoned after the bounded number of attempts); ``notes`` are non-blocking findings.

  structure       content kind matches the planned task; requested item count is respected
  grounding_pages every quiz/exercise ``source_pages`` entry is a page of the passages retrieved for
                  this request (only when retrieval returned passages)
  citations       explanation citations the GenAI module had to remove (it strips them before display)
"""

from __future__ import annotations

from ..schemas.content import (
    ConceptCardsContent,
    EducationalContent,
    ExplanationContent,
    FlashcardsContent,
    QuizContent,
    QuizItem,
    RemediationContent,
)
from ..schemas.ui import VerificationReport
from ..state import WorkflowPlan

STRUCTURE = "structure"
GROUNDING = "grounding_pages"
CITATIONS = "citations"


def _item_count(content: EducationalContent) -> int | None:
    if isinstance(content, QuizContent):
        return len(content.items)
    if isinstance(content, FlashcardsContent):
        return len(content.cards)
    if isinstance(content, ConceptCardsContent):
        return len(content.concepts)
    if isinstance(content, RemediationContent):
        return len(content.exercise.items)
    return None


def _quiz_items(content: EducationalContent) -> list[QuizItem]:
    if isinstance(content, QuizContent):
        return content.items
    if isinstance(content, RemediationContent):
        return content.exercise.items
    return []


def check_structure(plan: WorkflowPlan, content: EducationalContent) -> list[str]:
    """Contract-level validity is already enforced by Pydantic; this checks task fit."""
    if plan.task is None or content.kind != plan.task.value:
        return ["content_kind_mismatch"]
    count = _item_count(content)
    if plan.n_items is not None and count is not None and count != plan.n_items:
        return ["item_count_mismatch"]
    return []


def check_grounding(
    content: EducationalContent, context_pages: set[int]
) -> tuple[list[str], list[str]]:
    items = _quiz_items(content)
    issues, notes = [], []
    if any(not item.source_pages for item in items):
        notes.append("missing_source_pages")
    if any(page not in context_pages for item in items for page in item.source_pages):
        issues.append("source_page_outside_context")
    return issues, notes


def verify(
    plan: WorkflowPlan,
    content: EducationalContent,
    *,
    context_pages: set[int] | None = None,
    invalid_citations: list[int] | None = None,
) -> VerificationReport:
    checks, issues, notes = [STRUCTURE], check_structure(plan, content), []
    if context_pages and _quiz_items(content):
        checks.append(GROUNDING)
        found, grounding_notes = check_grounding(content, context_pages)
        issues += found
        notes += grounding_notes
    if isinstance(content, ExplanationContent) and invalid_citations is not None:
        checks.append(CITATIONS)
        if invalid_citations:
            notes.append("invalid_citations_removed")
    return VerificationReport(checks_run=checks, passed=not issues, issues=issues, notes=notes)
