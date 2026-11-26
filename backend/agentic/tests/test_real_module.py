"""Opt-in: the adapters against the GenAI module's REAL ``Tutor`` and ``VectorStore``.

Real here: ingestion, chunking, E5 embeddings, ChromaDB, hybrid BM25 search, the module's prompts and
output schemas, citation guard. NOT real: the LLM (a stub that answers from the prompt it receives),
so generation *quality* is not tested. Needs ``pip install -e <repo root>`` and downloads the embedding
model on first run, hence off by default:

    TUTOR_REAL_MODULE=1 pytest tests/test_real_module.py
"""

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TUTOR_REAL_MODULE"),
    reason="set TUTOR_REAL_MODULE=1 (needs the real GenAI module)",
)
pytest.importorskip("chromadb")
pytest.importorskip("sentence_transformers")

from tuteur.chunking import chunk_document  # noqa: E402
from tuteur.config import Settings as TuteurSettings  # noqa: E402
from tuteur.generation import Tutor  # noqa: E402
from tuteur.ingestion import load_document  # noqa: E402
from tuteur.schemas import Quiz, QuizItem, Remediation  # noqa: E402
from tuteur.vectorstore import VectorStore  # noqa: E402

from tutor_agentic.assets import AssetRegistry  # noqa: E402
from tutor_agentic.integrations.contracts import RetrievalRequest  # noqa: E402
from tutor_agentic.integrations.tuteur_backend import (  # noqa: E402
    TuteurAnswerEvaluationAdapter,
    TuteurGenerationAdapter,
    TuteurRetrievalAdapter,
)
from tutor_agentic.schemas.common import PresentationFormat  # noqa: E402
from tutor_agentic.schemas.requests import AnswerSubmission, ExperienceRequest, StudentAnswer  # noqa: E402

from .fake_tutor import CANNED_LLM  # noqa: E402

COURSE_FILE = Path(__file__).resolve().parents[3] / "data" / "raw" / "photosynthese.md"


class StubLLM:
    """Answers from the passages in the prompt, so page checks exercise the real retrieval."""

    model = "stub-llm"

    def _page(self, user: str) -> int:
        match = re.search(r"(?:page |\[p\. )(\d+)", user)
        return int(match.group(1)) if match else 1

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        # The second citation is deliberately invalid: the module's guard must remove it.
        return f"La chlorophylle capte la lumière [p. {self._page(user)}]. Elle est verte [p. 99]."

    def structured(self, system: str, user: str, schema: type, retries: int = 1):
        page = self._page(user)
        item = {
            "type": "qcm",
            "question": "Quel pigment capte la lumière ?",
            "choices": ["Chlorophylle", "Glucose", "Dioxygène", "Amidon"],
            "answer": "Chlorophylle",
            "explanation": "Cours.",
            "difficulty": "moyen",
            "competence": "Pigments",
            "source_pages": [page],
        }
        if schema is Quiz:
            n = int(re.search(r"Génère (\d+) questions", user).group(1))
            return Quiz(items=[QuizItem(**item) for _ in range(n)])
        if schema is Remediation:
            exercise = {**item, "type": "flashcard", "choices": [], "answer": "du dioxygène"}
            return Remediation(
                diagnostic="Confusion possible.",
                explanation="Rappel.",
                exercise=QuizItem(**exercise),
            )
        return schema.model_validate(CANNED_LLM[schema.__name__])


@pytest.fixture(scope="module")
def tutor(tmp_path_factory):
    settings = TuteurSettings(
        chroma_dir=tmp_path_factory.mktemp("chroma"),
        images_dir=tmp_path_factory.mktemp("img"),
        _env_file=None,
    )
    store = VectorStore(settings)
    document = load_document(COURSE_FILE)
    store.add(chunk_document(document, settings.chunk_size, settings.chunk_overlap))
    real = Tutor(store=store, llm=StubLLM())
    real.doc_id = document.doc_id
    return real


@pytest.fixture
def service(tutor, make_service, adapter_kwargs, tmp_path):
    return make_service(
        retrieval=TuteurRetrievalAdapter(tutor, AssetRegistry(), tmp_path, **adapter_kwargs),
        generation=TuteurGenerationAdapter(tutor, **adapter_kwargs),
        evaluation=TuteurAnswerEvaluationAdapter(tutor, **adapter_kwargs),
    )


async def test_retrieval_adapter_on_the_real_vector_store(tutor, adapter_kwargs, tmp_path):
    adapter = TuteurRetrievalAdapter(tutor, AssetRegistry(), tmp_path, **adapter_kwargs)
    found = await adapter.retrieve(
        RetrievalRequest(query="pourquoi les feuilles sont vertes", course_id=tutor.doc_id)
    )
    assert found.chunks and {c.source.doc_id for c in found.chunks} == {tutor.doc_id}
    assert any("chlorophylle" in c.text.lower() for c in found.chunks)
    assert found.simulated is False
    assert (
        await adapter.retrieve(RetrievalRequest(query="photosynthèse", course_id="inconnu"))
    ).chunks == []


async def test_full_loop_on_the_real_module(tutor, service, student):
    quiz = await service.create_experience(
        student,
        ExperienceRequest(
            message="Quiz me",
            course_id=tutor.doc_id,
            topic="photosynthèse chlorophylle lumière",
            requested_format=PresentationFormat.QUIZ,
        ),
    )
    report = quiz.ui.meta.verification
    assert quiz.status.value == "ok", quiz.ui.meta.warnings
    assert report.passed and "grounding_pages" in report.checks_run
    assert quiz.ui.meta.simulated is False
    question = quiz.ui.blocks[0].questions[0]
    assert len(question.options) == 4

    wrong = await service.submit_answer(
        student,
        AnswerSubmission(
            question_id=question.question_id, answer=StudentAnswer(selected_option_id="b")
        ),
    )
    kinds = [b.type for b in wrong.ui.blocks]
    assert kinds[0] == "quiz_feedback" and "quiz" in kinds and kinds[-1] == "recommendation_card"
    assert wrong.ui.meta.verification.passed


async def test_explanation_goes_through_the_modules_citation_guard(tutor, service, student):
    response = await service.create_experience(
        student,
        ExperienceRequest(
            message="Pourquoi les feuilles sont vertes ?",
            course_id=tutor.doc_id,
            topic="chlorophylle",
        ),
    )
    text = " ".join(b.text for b in response.ui.blocks if b.type == "text")
    assert "[p. 99]" not in text and "[p. 1]" in text  # invalid citation removed, valid one kept
    assert "invalid_citations_removed" in response.ui.meta.warnings
