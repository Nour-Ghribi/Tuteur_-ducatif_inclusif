"""Deterministic mocks of teammate services for local development and tests.

They implement the same contracts as the real services, mark every response ``simulated=True``
and contain no model, index or policy: they only exist so the orchestration can run end to end
before the real services are available. They go through the same resilience wrapper as the HTTP
adapters, and ``FaultInjector`` lets tests exercise timeouts, outages and malformed output.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Literal

from ..errors import AdapterRejected, AdapterUnavailable, MalformedResponse
from ..schemas.common import ActivityType, Difficulty, SourceRef
from ..schemas.content import GenerationTask
from .base import ResilientAdapter
from .contracts import (
    AnswerEvaluationRequest,
    AnswerEvaluationResponse,
    ColorAdaptationRequest,
    ColorAdaptationResponse,
    GenerationRequest,
    GenerationResponse,
    ImageDescriptionRequest,
    ImageDescriptionResponse,
    IntentClassificationRequest,
    IntentClassificationResponse,
    LearningSummariesRequest,
    LearningSummariesResponse,
    OutcomeAckResponse,
    OutcomeReport,
    RecommendationServiceRequest,
    RecommendationServiceResponse,
    RetrievalRequest,
    RetrievalResponse,
    RetrievedChunk,
    TopicAggregate,
)

MOCK_VERSION = "mock-0.1"

FaultKind = Literal["timeout", "unavailable", "rejected", "malformed"]


@dataclass
class FaultInjector:
    """Fails the first ``times`` calls (``times=-1``: every call) with the given fault."""

    kind: FaultKind
    times: int = -1
    calls: int = 0

    async def apply(self, service: str, operation: str) -> None:
        self.calls += 1
        if self.times != -1 and self.calls > self.times:
            return
        if self.kind == "timeout":
            await asyncio.sleep(3600)  # the resilience wrapper's timeout fires first
        elif self.kind == "unavailable":
            raise AdapterUnavailable(service, operation, "injected outage")
        elif self.kind == "rejected":
            raise AdapterRejected(service, operation, "injected rejection")
        else:
            raise MalformedResponse(service, operation, "injected malformed output")


class _MockAdapter(ResilientAdapter):
    def __init__(self, *, faults: FaultInjector | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.faults = faults
        self.calls = 0

    async def _mock(self, operation: str, build):
        async def call():
            self.calls += 1
            if self.faults:
                await self.faults.apply(self.service, operation)
            return build()

        return await self._invoke(operation, call)


# --- RAG ---------------------------------------------------------------------------------------

SYNTHETIC_CORPUS: dict[str, list[tuple[str, int, str]]] = {
    "demo-bio-101": [
        (
            "photosynthese",
            1,
            "La photosynthèse est le processus par lequel les plantes vertes transforment "
            "l'énergie lumineuse en énergie chimique. Elle se déroule dans les chloroplastes.",
        ),
        (
            "photosynthese",
            1,
            "La chlorophylle est le pigment qui absorbe la lumière. Elle donne aux feuilles "
            "leur couleur verte.",
        ),
        (
            "photosynthese",
            2,
            "Les réactifs de la photosynthèse sont le dioxyde de carbone et l'eau. Les produits "
            "sont le glucose et le dioxygène.",
        ),
        (
            "photosynthese",
            2,
            "La phase lumineuse produit de l'ATP et du NADPH. La phase sombre, ou cycle de "
            "Calvin, fixe le dioxyde de carbone pour produire du glucose.",
        ),
        (
            "respiration",
            3,
            "La respiration cellulaire dégrade le glucose pour libérer de l'énergie sous forme "
            "d'ATP. Elle consomme du dioxygène et rejette du dioxyde de carbone.",
        ),
    ],
}


def _tokens(value: str) -> set[str]:
    return {t for t in re.findall(r"\w+", value.lower()) if len(t) > 3}


class MockRetrievalAdapter(_MockAdapter):
    service = "rag"

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        def build() -> RetrievalResponse:
            query = _tokens(request.query)
            scored = []
            for index, (doc_id, page, passage) in enumerate(
                SYNTHETIC_CORPUS.get(request.course_id, [])
            ):
                overlap = len(query & _tokens(passage))
                if overlap:
                    scored.append((overlap, index, doc_id, page, passage))
            scored.sort(key=lambda item: (-item[0], item[1]))
            chunks = [
                RetrievedChunk(
                    chunk_id=f"{request.course_id}-c{index}",
                    text=passage,
                    source=SourceRef(
                        doc_id=doc_id, chunk_id=f"{request.course_id}-c{index}", page=page
                    ),
                    score=float(overlap),
                )
                for overlap, index, doc_id, page, passage in scored[: request.top_k]
            ]
            return RetrievalResponse(chunks=chunks, index_version=MOCK_VERSION, simulated=True)

        return await self._mock("retrieve", build)


# --- GenAI -------------------------------------------------------------------------------------

_LABELS = {
    "fr": {
        "about": "À propos de",
        "which_true": "Selon le cours, quelle affirmation est correcte ?",
        "distractor": "Affirmation simulée incorrecte",
        "notion": "Notion",
        "step": "Étape",
        "summary": "Synthèse simulée",
    },
    "en": {
        "about": "About",
        "which_true": "According to the course, which statement is correct?",
        "distractor": "Simulated incorrect statement",
        "notion": "Concept",
        "step": "Step",
        "summary": "Simulated summary",
    },
}


def _sentence_pages(request: GenerationRequest) -> list[tuple[str, int | None]]:
    found = [
        (s.strip(), passage.page)
        for passage in request.context
        for s in re.split(r"(?<=[.!?])\s+", passage.text)
        if s.strip()
    ]
    return found or [(f"{request.topic}.", None)]


def _sentences(request: GenerationRequest) -> list[str]:
    return [s for s, _ in _sentence_pages(request)]


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def build_mock_content(request: GenerationRequest) -> dict:
    """Assemble contract-valid content from the provided passages (no model involved)."""
    labels = _LABELS["en" if (request.preferences.language or "fr").startswith("en") else "fr"]
    sentences = _sentences(request)
    segment = request.preferences.max_segment_chars
    topic = _clip(request.topic, 200)
    n = request.n_items or 5

    def pick(i: int) -> str:
        return sentences[i % len(sentences)]

    def pages_of(i: int) -> list[int]:
        page = _sentence_pages(request)[i % len(sentences)][1]
        return [page] if page else []

    def quiz(count: int) -> dict:
        items = []
        for i in range(count):
            items.append(
                {
                    "item_id": f"q{i + 1}",
                    "item_type": "mcq",
                    "prompt": labels["which_true"],
                    "options": [
                        {"option_id": "a", "text": _clip(pick(i), 500)},
                        {"option_id": "b", "text": f"{labels['distractor']} 1"},
                        {"option_id": "c", "text": f"{labels['distractor']} 2"},
                    ],
                    "correct_option_id": "a",
                    "explanation": _clip(pick(i), 2000),
                    "difficulty": (request.difficulty or Difficulty.MEDIUM).value,
                    "source_pages": pages_of(i),
                }
            )
        return {"kind": "quiz", "title": topic, "items": items}

    def explanation() -> dict:
        return {
            "kind": "explanation",
            "title": topic,
            "sections": [{"body": _clip(s, segment)} for s in sentences[:4]],
            "key_points": [_clip(s, 300) for s in sentences[:3]],
        }

    task = request.task
    if task is GenerationTask.EXPLANATION:
        return explanation()
    if task is GenerationTask.QUIZ:
        return quiz(n)
    if task is GenerationTask.FLASHCARDS:
        return {
            "kind": "flashcards",
            "title": topic,
            "cards": [
                {
                    "front": f"{labels['notion']} {i + 1} — {topic}"[:300],
                    "back": _clip(pick(i), 1000),
                }
                for i in range(min(n, 30))
            ],
        }
    if task is GenerationTask.CONCEPT_CARDS:
        return {
            "kind": "concept_cards",
            "title": topic,
            "concepts": [
                {"term": f"{labels['notion']} {i + 1}", "definition": _clip(pick(i), 1000)}
                for i in range(min(n, 20))
            ],
        }
    if task is GenerationTask.CONCEPT_MAP:
        nodes = [{"node_id": "root", "label": topic[:120]}] + [
            {"node_id": f"n{i + 1}", "label": _clip(s, 120)} for i, s in enumerate(sentences[:6])
        ]
        return {
            "kind": "concept_map",
            "title": topic,
            "central_node_id": "root",
            "nodes": nodes,
            "edges": [{"source": "root", "target": n["node_id"]} for n in nodes[1:]],
        }
    if task is GenerationTask.STEPS:
        return {
            "kind": "steps",
            "title": topic,
            "steps": [
                {"title": f"{labels['step']} {i + 1}", "detail": _clip(s, segment)}
                for i, s in enumerate(sentences[:6])
            ],
        }
    if task is GenerationTask.COMPARISON:
        return {
            "kind": "comparison",
            "title": topic,
            "items": ["A", "B"],
            "rows": [
                {
                    "criterion": f"{labels['notion']} {i + 1}",
                    "values": [_clip(pick(i), 500), _clip(pick(i + 1), 500)],
                }
                for i in range(min(3, len(sentences)))
            ],
        }
    if task is GenerationTask.REMEDIATION:
        return {
            "kind": "remediation",
            "diagnostic": f"[simulated] {topic}",
            "explanation": _clip(" ".join(sentences[:3]), 4000),
            "exercise": quiz(1),
        }
    # REPORT_SUMMARY: built from aggregates only.
    weakest = sorted(request.report_aggregates or [], key=lambda t: t.success_rate)[:3]
    return {
        "kind": "report_summary",
        "summary": f"{labels['summary']} — {topic}.",
        "recurring_difficulties": [t.topic for t in weakest],
    }


class MockContentGenerationAdapter(_MockAdapter):
    service = "genai"

    def __init__(self, *, content_override: dict | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.content_override = content_override  # lets tests inject malformed/mismatched output
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)

        def build() -> GenerationResponse:
            content = self.content_override or build_mock_content(request)
            return GenerationResponse.model_validate(
                {
                    "content": content,
                    "prompt_version": MOCK_VERSION,
                    "model_id": "mock-template",
                    "pages_used": sorted({p.page for p in request.context if p.page}),
                    "simulated": True,
                }
            )

        return await self._mock("generate", build)


class MockAnswerEvaluationAdapter(_MockAdapter):
    service = "genai"

    async def evaluate(self, request: AnswerEvaluationRequest) -> AnswerEvaluationResponse:
        def build() -> AnswerEvaluationResponse:
            reference = _tokens(request.reference_answer)
            overlap = len(reference & _tokens(request.student_answer)) / max(len(reference), 1)
            score = round(min(overlap, 1.0), 2)
            return AnswerEvaluationResponse(
                is_correct=score >= 0.5,
                score=score,
                observed_errors=[] if score >= 0.5 else ["missing_key_terms"],
                model_id="mock-keyword-overlap",
                simulated=True,
            )

        return await self._mock("evaluate_answer", build)


class MockIntentClassifierAdapter(_MockAdapter):
    service = "genai"

    def __init__(self, *, answer: str | None = None, confidence: float = 0.9, **kwargs) -> None:
        super().__init__(**kwargs)
        self.answer = answer
        self.confidence = confidence

    async def classify(self, request: IntentClassificationRequest) -> IntentClassificationResponse:
        def build() -> IntentClassificationResponse:
            return IntentClassificationResponse(
                intent=self.answer or request.allowed_intents[0],
                confidence=self.confidence,
                simulated=True,
            )

        return await self._mock("classify_intent", build)


class MockInclusionAdapter(_MockAdapter):
    service = "inclusion"

    async def describe_image(self, request: ImageDescriptionRequest) -> ImageDescriptionResponse:
        return await self._mock(
            "describe_image",
            lambda: ImageDescriptionResponse(
                alt_text="[simulated] image description placeholder",
                model_id="mock",
                simulated=True,
            ),
        )

    async def adapt_colors(self, request: ColorAdaptationRequest) -> ColorAdaptationResponse:
        return await self._mock(
            "adapt_colors",
            lambda: ColorAdaptationResponse(
                adapted_image_ref=request.image_ref, method="mock-identity", simulated=True
            ),
        )


# --- RL ----------------------------------------------------------------------------------------


class MockRecommendationAdapter(_MockAdapter):
    """Fixed heuristic standing in for the RL policy. It is not a trained policy."""

    service = "rl"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.outcomes: list[OutcomeReport] = []

    async def recommend(
        self, request: RecommendationServiceRequest
    ) -> RecommendationServiceResponse:
        def build() -> RecommendationServiceResponse:
            scores = request.features.recent_scores
            mean = sum(scores) / len(scores) if scores else None
            if request.features.last_outcome == "incorrect" or (mean is not None and mean < 0.5):
                wanted = [
                    (ActivityType.REVISION, Difficulty.EASY),
                    (ActivityType.QUIZ, Difficulty.EASY),
                ]
            elif mean is not None and mean >= 0.8:
                wanted = [
                    (ActivityType.QUIZ, Difficulty.HARD),
                    (ActivityType.EXERCISE, Difficulty.HARD),
                ]
            else:
                wanted = [(ActivityType.QUIZ, Difficulty.MEDIUM)]
            options = request.available_activities
            choice = next(
                (o for w in wanted for o in options if (o.activity_type, o.difficulty) == w),
                options[0],
            )
            return RecommendationServiceResponse(
                recommendation_id=f"rec-{uuid.uuid4().hex[:12]}",
                activity_type=choice.activity_type,
                difficulty=choice.difficulty,
                topic=choice.topic,
                policy_version="mock-heuristic-0",
                simulated=True,
            )

        return await self._mock("recommend", build)

    async def report_outcome(self, request: OutcomeReport) -> OutcomeAckResponse:
        def build() -> OutcomeAckResponse:
            self.outcomes.append(request)
            return OutcomeAckResponse(accepted=True, simulated=True)

        return await self._mock("report_outcome", build)


# --- Learning records --------------------------------------------------------------------------


class MockLearningRecordsAdapter(_MockAdapter):
    """Synthetic aggregates. They do not describe any real learner."""

    service = "learning_records"

    async def summaries(self, request: LearningSummariesRequest) -> LearningSummariesResponse:
        def build() -> LearningSummariesResponse:
            seed = int(hashlib.sha256(request.class_id.encode()).hexdigest()[:8], 16)
            topics = [
                TopicAggregate(
                    topic=name,
                    attempts=40 + (seed >> shift) % 60,
                    success_rate=round(0.35 + ((seed >> shift) % 50) / 100, 2),
                    median_time_s=float(30 + (seed >> shift) % 90),
                    common_error_tags=tags,
                )
                for shift, name, tags in (
                    (0, "photosynthese", ["confusion_reactifs_produits"]),
                    (4, "chlorophylle", []),
                    (8, "respiration", ["confusion_photosynthese_respiration"]),
                )
            ]
            return LearningSummariesResponse(
                class_id=request.class_id,
                period_start=request.period_start,
                period_end=request.period_end,
                learner_count=12 + seed % 18,
                topics=topics,
                simulated=True,
            )

        return await self._mock("summaries", build)
