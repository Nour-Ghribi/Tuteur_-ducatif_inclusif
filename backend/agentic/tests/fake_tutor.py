"""A stand-in for the GenAI module's ``Tutor`` that returns the module's REAL output models.

Only ``tuteur.schemas`` is imported (pure Pydantic), so tests need neither chromadb, nor embeddings,
nor an LLM key. Conversions are therefore checked against the teammates' actual schema.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from tuteur.schemas import Answer, Quiz, QuizItem, Remediation

CORPUS = [
    (
        "c0",
        "doc1",
        1,
        "La chlorophylle est le pigment vert qui capte la lumière dans les chloroplastes.",
        True,
    ),
    (
        "c1",
        "doc1",
        2,
        "La photosynthèse produit du glucose et rejette du dioxygène dans l'atmosphère.",
        False,
    ),
    (
        "c2",
        "doc1",
        3,
        "La respiration consomme du dioxygène et rejette du dioxyde de carbone.",
        False,
    ),
    ("o0", "doc2", 1, "Un autre cours parle de photosynthèse dans un autre document.", False),
]
CANNED_LLM = {
    "ConceptMapContent": {
        "kind": "concept_map",
        "title": "Photosynthèse",
        "central_node_id": "root",
        "nodes": [
            {"node_id": "root", "label": "Photosynthèse"},
            {"node_id": "n1", "label": "Chlorophylle"},
        ],
        "edges": [{"source": "root", "target": "n1", "label": "utilise"}],
    },
    "StepsContent": {
        "kind": "steps",
        "title": "Photosynthèse",
        "steps": [{"title": "Capter la lumière", "detail": "La chlorophylle capte la lumière."}],
    },
    "ComparisonContent": {
        "kind": "comparison",
        "title": "Photosynthèse et respiration",
        "items": ["Photosynthèse", "Respiration"],
        "rows": [{"criterion": "Gaz rejeté", "values": ["Dioxygène", "Dioxyde de carbone"]}],
    },
    "ConceptCardsContent": {
        "kind": "concept_cards",
        "title": "Notions clés",
        "concepts": [{"term": "Chlorophylle", "definition": "Pigment vert qui capte la lumière."}],
    },
    "ReportSummaryContent": {
        "kind": "report_summary",
        "summary": "Synthèse des indicateurs agrégés.",
        "recurring_difficulties": ["respiration"],
    },
    "GradeResult": {
        "is_correct": True,
        "score": 0.9,
        "observed_errors": [],
        "rationale": "Même idée.",
    },
    "IntentResult": {"intent": "flashcards", "confidence": 0.95},
}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"\w+", text.lower()) if len(t) > 3}


class FakeLLM:
    model = "fake-llm"

    def __init__(self, overrides: dict[str, Any] | None = None) -> None:
        self.overrides = overrides or {}
        self.calls: list[tuple[str, str, str]] = []

    def structured(self, system: str, user: str, schema: type, retries: int = 1):
        self.calls.append((system, user, schema.__name__))
        return schema.model_validate(
            self.overrides.get(schema.__name__, CANNED_LLM[schema.__name__])
        )


class FakeStore:
    settings = SimpleNamespace(embedding_model="fake-e5")

    def search(
        self, query: str, k: int | None = None, where: dict | None = None, mode: str | None = None
    ):
        wanted = (where or {}).get("doc_id")
        scored = []
        for cid, doc_id, page, text, has_images in CORPUS:
            if wanted and doc_id != wanted:
                continue
            if overlap := len(_tokens(query) & _tokens(text)):
                meta = {
                    "doc_id": doc_id,
                    "source": f"{doc_id}.pdf",
                    "page": page,
                    "has_images": has_images,
                }
                scored.append(
                    (
                        overlap,
                        SimpleNamespace(id=cid, text=text, metadata=meta, score=float(overlap)),
                    )
                )
        scored.sort(key=lambda t: -t[0])
        return [r for _, r in scored[: k or 5]]


def _qcm(i: int, page: int = 1, answer: str = "Chlorophylle") -> QuizItem:
    return QuizItem(
        type="qcm",
        question=f"Quel pigment capte la lumière ? ({i})",
        choices=["Carotène", answer, "Glucose", "Dioxygène"],
        answer=answer,
        explanation="La chlorophylle capte la lumière.",
        difficulty="moyen",
        competence="Pigments",
        source_pages=[page],
    )


class FakeTutor:
    def __init__(self, llm: FakeLLM | None = None) -> None:
        self.store = FakeStore()
        self.llm = llm or FakeLLM()
        self.calls: list[tuple[str, dict]] = []
        self.fail_with: Exception | None = None

    def _maybe_fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    def ask(self, question: str, reading_level: str = "standard", k: int | None = None) -> Answer:
        self.calls.append(("ask", {"question": question, "reading_level": reading_level}))
        self._maybe_fail()
        return Answer(
            text="La chlorophylle capte la lumière [p. 1].\n\nElle est verte [p. 7].",
            raw_text="",
            invalid_citations=[7],
            sources=[],
            contexts=[],
            context_pages=[1, 2],
            prompt="answer@v3",
        )

    def quiz(
        self,
        *,
        topic=None,
        doc_id=None,
        pages=None,
        n=5,
        difficulty="moyen",
        types=("qcm", "vrai_faux", "flashcard"),
        reading_level="standard",
    ) -> Quiz:
        self.calls.append(
            ("quiz", {"topic": topic, "n": n, "types": types, "difficulty": difficulty})
        )
        self._maybe_fail()
        if types == ("flashcard",):
            items = [
                QuizItem(
                    type="flashcard",
                    question=f"Qu'est-ce que la chlorophylle ? ({i})",
                    choices=[],
                    answer="Le pigment vert",
                    explanation="Cours p.1",
                    difficulty=difficulty,
                    competence="Pigments",
                    source_pages=[1],
                )
                for i in range(n)
            ]
        else:
            items = [
                _qcm(i)
                if i % 2 == 0
                else QuizItem(
                    type="vrai_faux",
                    question=f"La photosynthèse rejette du dioxygène. ({i})",
                    choices=[],
                    answer="Vrai",
                    explanation="Cours p.2",
                    difficulty=difficulty,
                    competence="Produits",
                    source_pages=[2],
                )
                for i in range(n)
            ]
        return Quiz(items=items)

    def remediate(
        self, question, student_answer, correct_answer, history=None, reading_level="standard"
    ) -> Remediation:
        self.calls.append(
            (
                "remediate",
                {
                    "question": question,
                    "student_answer": student_answer,
                    "correct_answer": correct_answer,
                    "history": history,
                },
            )
        )
        self._maybe_fail()
        # Like the real module, the exercise cites the pages of the passages searched for this error.
        hits = self.store.search(f"{question} {correct_answer}")
        page = hits[0].metadata["page"] if hits else 1
        return Remediation(
            diagnostic="Tu as peut-être confondu photosynthèse et respiration.",
            explanation="La photosynthèse rejette du dioxygène ; la respiration en consomme.",
            exercise=QuizItem(
                type="flashcard",
                question="Que consomme la respiration ?",
                choices=[],
                answer="du dioxygène",
                explanation=f"Cours p.{page}",
                difficulty="facile",
                competence="Respiration",
                source_pages=[page],
            ),
        )
