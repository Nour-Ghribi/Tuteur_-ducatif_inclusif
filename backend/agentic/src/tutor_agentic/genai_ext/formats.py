"""Generation of the formats the GenAI module does not provide yet, plus grading and intent
classification. All of them reuse the GenAI module's LLM client (``llm.structured``: JSON mode,
Pydantic validation and one corrective retry), so model choice, keys and tracing stay in one place.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from ..integrations.contracts import ContextPassage, GenerationRequest, TopicAggregate
from ..schemas.content import (
    ComparisonContent,
    ConceptCardsContent,
    ConceptMapContent,
    EducationalContent,
    GenerationTask,
    ReportSummaryContent,
    StepsContent,
)
from .loader import load_ext_prompt

TASK_SCHEMA: dict[GenerationTask, tuple[str, type[BaseModel]]] = {
    GenerationTask.CONCEPT_MAP: ("concept_map", ConceptMapContent),
    GenerationTask.STEPS: ("steps", StepsContent),
    GenerationTask.COMPARISON: ("comparison", ComparisonContent),
    GenerationTask.CONCEPT_CARDS: ("concept_cards", ConceptCardsContent),
}


class GradeResult(BaseModel):
    is_correct: bool
    score: float = Field(ge=0, le=1)
    observed_errors: list[str] = Field(default_factory=list, max_length=10)
    rationale: str | None = None


class IntentResult(BaseModel):
    intent: str
    confidence: float = Field(ge=0, le=1)


def format_passages(passages: list[ContextPassage]) -> str:
    """Same passage header as the GenAI module's ``answer.v3``: the page is outside the course text."""
    return "\n\n".join(
        f"=== PASSAGE {i} — page {p.page or '?'} ===\n{p.text}" for i, p in enumerate(passages, 1)
    )


def _reading_level(request: GenerationRequest) -> str:
    return "simplifie" if request.preferences.reading_level == "simplified" else "standard"


def generate_format(llm: Any, request: GenerationRequest) -> tuple[EducationalContent, str]:
    """Returns (content, prompt tag). ``llm`` is the GenAI module's ``LLM`` instance."""
    name, schema = TASK_SCHEMA[request.task]
    prompt = load_ext_prompt(name)
    system, user = prompt.render(
        _reading_level(request),
        context=format_passages(request.context),
        topic=request.topic,
        request=request.learner_request or request.topic,
        n=str(request.n_items or 6),
    )
    if request.critic_feedback:
        user += "\n\nCorrige ces problèmes détectés à la relecture : " + ", ".join(
            request.critic_feedback
        )
    return llm.structured(system, user, schema), prompt.tag


def summarize_report(
    llm: Any, aggregates: list[TopicAggregate], period: str
) -> tuple[EducationalContent, str]:
    prompt = load_ext_prompt("report_summary")
    table = json.dumps([a.model_dump() for a in aggregates], ensure_ascii=False)
    system, user = prompt.render("standard", period=period, aggregates=table)
    return llm.structured(system, user, ReportSummaryContent), prompt.tag


def grade_answer(llm: Any, question: str, reference: str, answer: str) -> GradeResult:
    prompt = load_ext_prompt("grade")
    system, user = prompt.render("standard", question=question, reference=reference, answer=answer)
    return llm.structured(system, user, GradeResult)


def classify_intent(llm: Any, message: str, allowed: list[str]) -> IntentResult:
    prompt = load_ext_prompt("intent")
    system, user = prompt.render("standard", intents=", ".join(allowed), message=message)
    return llm.structured(system, user, IntentResult)
