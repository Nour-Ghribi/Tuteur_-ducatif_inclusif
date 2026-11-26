"""In-process adapters over the GenAI + RAG module (``tuteur``), owned by the GenAI/RAG teammates.

The module is a Python library, not a service, so these adapters call ``Tutor`` directly (in a
worker thread, behind the same timeout/retry wrapper as the HTTP adapters). Nothing of the module is
reimplemented: retrieval is ``Tutor.store.search``, generation is ``Tutor.ask/quiz/remediate`` and
the added formats reuse ``Tutor.llm.structured``. When the teammates expose an HTTP service, switch
``TUTOR_GENAI_BACKEND=http``; the graph does not change.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..assets import AssetRegistry
from ..config import Settings
from ..errors import AdapterError, AdapterRejected, AdapterTimeout, AdapterUnavailable
from ..genai_ext import classify_intent, generate_format, grade_answer, summarize_report
from ..schemas.common import SourceRef
from ..schemas.content import (
    ExplanationContent,
    FlashcardsContent,
    GenerationTask,
    QuizContent,
    RemediationContent,
    Section,
)
from .base import ResilientAdapter
from .contracts import (
    AnswerEvaluationRequest,
    AnswerEvaluationResponse,
    GenerationRequest,
    GenerationResponse,
    IntentClassificationRequest,
    IntentClassificationResponse,
    RetrievalRequest,
    RetrievalResponse,
    RetrievedChunk,
)
from .convert import DIFFICULTY_TO_FR, cut, question_for, to_flashcard, to_quiz_item

FORMAT_TASKS = (
    GenerationTask.CONCEPT_MAP,
    GenerationTask.STEPS,
    GenerationTask.COMPARISON,
    GenerationTask.CONCEPT_CARDS,
)


def _translate(service: str, operation: str, exc: Exception) -> AdapterError:
    if isinstance(exc, ValueError):  # e.g. Tutor.quiz: "Aucun passage trouvé"
        return AdapterRejected(service, operation, "request rejected by the GenAI module")
    if type(exc).__name__ == "APITimeoutError" or isinstance(exc, TimeoutError):
        return AdapterTimeout(service, operation, "LLM timeout")
    return AdapterUnavailable(service, operation, type(exc).__name__)


class _TuteurAdapter(ResilientAdapter):
    def __init__(self, tutor: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tutor = tutor

    async def _in_thread(self, operation: str, fn: Callable[[], Any]) -> Any:
        async def call() -> Any:
            try:
                return await asyncio.to_thread(fn)
            except (AdapterError, ValidationError):
                raise
            except Exception as exc:
                raise _translate(self.service, operation, exc) from exc

        return await self._invoke(operation, call)


class TuteurRetrievalAdapter(_TuteurAdapter):
    service = "rag"

    def __init__(self, tutor: Any, assets: AssetRegistry, images_dir: Path, **kwargs: Any) -> None:
        super().__init__(tutor, **kwargs)
        self._assets = assets
        self._images_dir = images_dir

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        return await self._in_thread("retrieve", lambda: self._search(request))

    def _search(self, request: RetrievalRequest) -> RetrievalResponse:
        # course_id is the indexed document id (see `tuteur docs`).
        results = self._tutor.store.search(
            request.query, k=request.top_k, where={"doc_id": request.course_id}
        )
        chunks = []
        for r in results:
            doc_id, page = r.metadata["doc_id"], int(r.metadata["page"])
            chunks.append(
                RetrievedChunk(
                    chunk_id=r.id,
                    text=r.text,
                    source=SourceRef(doc_id=doc_id, chunk_id=r.id, page=page),
                    score=max(float(r.score), 0.0),
                    image_refs=self._image_refs(doc_id, page)
                    if r.metadata.get("has_images")
                    else [],
                )
            )
        return RetrievalResponse(
            chunks=chunks, index_version=self._tutor.store.settings.embedding_model
        )

    def _image_refs(self, doc_id: str, page: int) -> list[str]:
        files = sorted((self._images_dir / doc_id).glob(f"p{page}_img*.png"))
        return [self._assets.register(f).asset_id for f in files[:3]]


class TuteurGenerationAdapter(_TuteurAdapter):
    service = "genai"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return await self._in_thread("generate", lambda: self._generate(request))

    def _generate(self, request: GenerationRequest) -> GenerationResponse:
        tutor, task = self._tutor, request.task
        level = "simplifie" if request.preferences.reading_level == "simplified" else "standard"
        difficulty = DIFFICULTY_TO_FR[request.difficulty] if request.difficulty else "moyen"
        title = cut(request.topic, 200)
        pages: list[int] = []
        invalid: list[int] = []
        prompt_version: str | None = None

        if task is GenerationTask.QUIZ:
            quiz = tutor.quiz(
                topic=request.topic,
                n=request.n_items or 5,
                difficulty=difficulty,
                types=("qcm", "vrai_faux"),
                reading_level=level,
            )
            items = [to_quiz_item(i, f"q{n}") for n, i in enumerate(quiz.items, 1)]
            content = QuizContent(title=title, items=items)
            pages = sorted({p for i in items for p in i.source_pages})
        elif task is GenerationTask.FLASHCARDS:
            quiz = tutor.quiz(
                topic=request.topic,
                n=request.n_items or 8,
                difficulty=difficulty,
                types=("flashcard",),
                reading_level=level,
            )
            content = FlashcardsContent(title=title, cards=[to_flashcard(i) for i in quiz.items])
            pages = sorted({p for i in quiz.items for p in i.source_pages})
        elif task is GenerationTask.EXPLANATION:
            answer = tutor.ask(
                question_for(request.topic, request.learner_request), reading_level=level
            )
            paragraphs = [p.strip() for p in answer.text.split("\n\n") if p.strip()] or [
                answer.text.strip()
            ]
            content = ExplanationContent(
                title=title, sections=[Section(body=cut(p, 4000)) for p in paragraphs[:12]]
            )
            pages, invalid, prompt_version = (
                list(answer.context_pages),
                list(answer.invalid_citations),
                answer.prompt,
            )
        elif task is GenerationTask.REMEDIATION and request.remediation:
            r = request.remediation
            rem = tutor.remediate(
                r.question,
                r.student_answer,
                r.correct_answer,
                history=r.history or None,
                reading_level=level,
            )
            content = RemediationContent(
                diagnostic=cut(rem.diagnostic, 1000) if rem.diagnostic else None,
                explanation=cut(rem.explanation, 4000),
                exercise=QuizContent(title=title, items=[to_quiz_item(rem.exercise, "r1")]),
            )
            pages = sorted(set(rem.exercise.source_pages))
        elif task is GenerationTask.REPORT_SUMMARY:
            content, prompt_version = summarize_report(
                tutor.llm, request.report_aggregates or [], request.report_period or ""
            )
        elif task in FORMAT_TASKS:
            content, prompt_version = generate_format(tutor.llm, request)
            pages = sorted({p.page for p in request.context if p.page})
        else:
            raise ValueError(f"unsupported task {task}")
        return GenerationResponse(
            content=content,
            prompt_version=prompt_version,
            model_id=getattr(tutor.llm, "model", None),
            pages_used=pages,
            invalid_citations=invalid,
        )


class TuteurAnswerEvaluationAdapter(_TuteurAdapter):
    """LLM grader for open answers (the GenAI module has no grader of its own yet)."""

    service = "genai"

    async def evaluate(self, request: AnswerEvaluationRequest) -> AnswerEvaluationResponse:
        def run() -> AnswerEvaluationResponse:
            g = grade_answer(
                self._tutor.llm,
                request.question_prompt,
                request.reference_answer,
                request.student_answer,
            )
            return AnswerEvaluationResponse(
                is_correct=g.is_correct,
                score=g.score,
                observed_errors=[cut(e, 300) for e in g.observed_errors],
                rationale=cut(g.rationale, 2000) if g.rationale else None,
                model_id=getattr(self._tutor.llm, "model", None),
            )

        return await self._in_thread("evaluate_answer", run)


class TuteurIntentClassifierAdapter(_TuteurAdapter):
    service = "genai"

    async def classify(self, request: IntentClassificationRequest) -> IntentClassificationResponse:
        def run() -> IntentClassificationResponse:
            r = classify_intent(self._tutor.llm, request.message, request.allowed_intents)
            return IntentClassificationResponse(intent=r.intent, confidence=r.confidence)

        return await self._in_thread("classify_intent", run)


def build_tutor(settings: Settings) -> Any:
    """Constructs the GenAI module's ``Tutor`` (needs ``pip install -e .`` of the repo root)."""
    from tuteur.generation import Tutor  # lazy: heavy imports (chromadb, sentence-transformers)

    tutor = Tutor()
    # The module's client retries 8 times with no timeout: fine for a CLI, but it would hang a request.
    tutor.llm.client = tutor.llm.client.with_options(
        timeout=settings.genai_timeout_s, max_retries=2
    )
    with contextlib.suppress(Exception):  # load the embedding model before the first request
        tutor.store.search("warm-up", k=1)
    return tutor
