"""Tests de bout en bout du RAG (vrai mod├¿le d'embedding, Chroma en m├®moire, LLM simul├®)."""

import json
import uuid
from pathlib import Path

import chromadb
import pytest

from tuteur.chunking import chunk_document
from tuteur.config import Settings
from tuteur.generation import Tutor
from tuteur.ingestion import load_document
from tuteur.llm import LLM
from tuteur.vectorstore import VectorStore

COURS = Path(__file__).parents[1] / "data" / "raw" / "photosynthese.md"


@pytest.fixture(scope="module")
def store():
    settings = Settings(collection=f"test-{uuid.uuid4().hex[:8]}", chunk_size=300, chunk_overlap=50)
    s = VectorStore(settings, client=chromadb.EphemeralClient())
    doc = load_document(COURS)
    s.add(chunk_document(doc, settings.chunk_size, settings.chunk_overlap))
    return s


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Pourquoi les feuilles sont-elles vertes ?", "chlorophylle"),
        ("Par o├╣ le CO2 entre-t-il dans la feuille ?", "stomates"),
        ("Quelle est la diff├®rence avec la respiration ?", "respiration"),
        ("Qu'est-ce que la plante produit ?", "glucose"),
    ],
)
def test_retrieval_finds_relevant_passage(store, question, expected):
    top = store.search(question, k=2)
    assert any(expected in r.text.lower() for r in top), [r.text[:80] for r in top]


@pytest.mark.parametrize("mode", ["dense", "hybride"])
def test_both_search_modes_find_stomates(store, mode):
    top = store.search("Par o├╣ le CO2 entre-t-il dans la feuille ?", k=3, mode=mode)
    assert len(top) == 3 and any("stomates" in r.text for r in top)


def test_hybrid_index_follows_new_chunks(store):
    from tuteur.chunking import Chunk

    store.search("chlorophylle", mode="hybride")  # construit l'index BM25
    store.add([Chunk(id="extra-p1-c0", text="Le xyl├¿me transporte la s├¿ve brute.",
                     metadata={"doc_id": "extra", "source": "extra.md", "page": 1, "has_images": False})])
    assert store.search("xyl├¿me", k=1, mode="hybride")[0].id == "extra-p1-c0"
    store.delete_document("extra")


def test_reingest_is_idempotent(store):
    before = store.collection.count()
    store.add(chunk_document(load_document(COURS), 300, 50))
    assert store.collection.count() == before


class FakeLLM(LLM):
    """Remplace le LLM : renvoie un quiz valide et garde les prompts re├ºus."""

    def __init__(self):
        self.prompts = []

    def chat(self, system, user, json_mode=False):
        self.prompts.append((system, user))
        item = dict(type="vrai_faux", question="La chlorophylle est verte.", choices=["Vrai", "Faux"],
                    answer="Vrai", explanation="Elle r├®fl├®chit le vert.", difficulty="facile",
                    competence="chlorophylle", source_pages=[1])
        return json.dumps({"items": [item]})


def test_quiz_pipeline_with_fake_llm(store):
    llm = FakeLLM()
    quiz = Tutor(store=store, llm=llm).quiz(topic="chlorophylle", n=1, reading_level="simplifie")
    assert quiz.items[0].answer == "Vrai"
    system, user = llm.prompts[0]
    assert "FALC" in system  # la consigne d'accessibilit├® est bien inject├®e
    assert "chlorophylle" in user.lower()  # le contexte RAG est bien pass├® au LLM
