"""Pipeline RAG batch réel, pour l'orchestration Airflow de la branche `mlops`.

Mêmes étapes, mêmes noms de fichiers et même manifeste (`registry/rag/latest.json`) que le
pipeline simulé `orchestration/tuteur_pipelines/rag_pipeline.py`, mais avec le vrai code du
tuteur : PyMuPDF, découpage 800/150, embeddings e5, ChromaDB + BM25, quiz par le LLM.
Chaque étape lit le fichier produit par la précédente et renvoie le chemin du sien, comme
le demandent les tâches Airflow (seuls des chemins passent entre les tâches).

    root/inputs/*.pdf|md|txt  ->  root/runs/rag/<run_id>/01_sources.json … 07_evaluation.json
                              ->  root/registry/rag/latest.json
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chromadb

from tuteur.chunking import chunk_document
from tuteur.config import Settings, get_settings
from tuteur.generation import Tutor
from tuteur.ingestion import Document, Page, load_document
from tuteur.llm import LLM
from tuteur.prompts import load_prompt, styles_tag
from tuteur.vectorstore import VectorStore

COURSE_SUFFIXES = (".pdf", ".md", ".txt")
COLLECTION = "cours"


# ---------- Utilitaires (même format que orchestration/tuteur_pipelines/common.py) ----------

def _safe_run_id(run_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", run_id).strip("_") or "manual"


def _run_dir(root: str | Path, run_id: str) -> Path:
    path = Path(root) / "runs" / "rag" / _safe_run_id(run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: str | Path, payload: Any) -> str:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(destination)  # écriture atomique : une tâche relancée ne lit jamais un fichier à moitié écrit
    return str(destination)


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _version(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "rag-" + hashlib.sha256(encoded).hexdigest()[:12]


def _score(value: float) -> float:
    return round(float(value), 4)  # mean() de booléens renvoie un int : on garde des décimaux dans le JSON


def _store(index_path: str | Path, settings: Settings | None = None) -> VectorStore:
    """Rouvre la base ChromaDB construite par `index_vectors` pour ce run."""
    index = _read_json(index_path)
    settings = (settings or get_settings()).model_copy(
        update={"chroma_dir": Path(index["chroma_dir"]), "collection": index["collection"]})
    return VectorStore(settings)


# ---------- Étapes du pipeline ----------

def load_course(root: str | Path, run_id: str) -> str:
    """1. Copie les cours de root/inputs/ dans le dossier du run (le run reste reproductible
    même si inputs/ change ensuite)."""
    inputs = Path(root) / "inputs"
    files = sorted(p for p in inputs.glob("*") if p.suffix.lower() in COURSE_SUFFIXES)
    if not files:
        raise FileNotFoundError(f"Aucun cours (PDF, MD, TXT) dans {inputs}")
    destination = _run_dir(root, run_id) / "01_sources"
    destination.mkdir(exist_ok=True)
    copies = [str(Path(shutil.copy2(f, destination / f.name)).resolve()) for f in files]
    return _write_json(destination.parent / "01_sources.json", {"files": copies})


def extract_and_clean(sources_path: str, describe_images: bool = True) -> str:
    """2. Texte page par page (PyMuPDF pour les PDF) ; description VLM des images si activée.

    Les pages vides sont gardées pour que les numéros de page restent ceux du document.
    Si VISION_MODEL est configuré et describe_images=True, chaque image extraite est décrite
    par le VLM avant le découpage — les sidecars .txt sont écrits à côté des PNGs.
    """
    from tuteur.vision import make_describer_from_settings
    settings = get_settings()
    describer = make_describer_from_settings(settings) if describe_images else None

    documents = []
    for path in _read_json(sources_path)["files"]:
        doc = load_document(
            Path(path),
            images_dir=settings.images_dir,
            describer=describer,
        )
        documents.append({
            "doc_id": doc.doc_id,
            "source": doc.source,
            "pages": [
                {
                    "number": p.number,
                    "text": p.text,
                    "images": [str(img) for img in p.images],
                }
                for p in doc.pages
            ],
        })
    if not any(p["text"] for d in documents for p in d["pages"]):
        raise ValueError("Les cours ne contiennent aucun texte extractible (PDF scanné ?).")
    return _write_json(Path(sources_path).parent / "02_pages.json", {"documents": documents})


def split_into_chunks(pages_path: str, chunk_size: int | None = None, chunk_overlap: int | None = None) -> str:
    """3. Découpage en passages (800 caractères, chevauchement 150 par défaut).

    Text chunks + image description chunks (from VLM sidecars) are both included.
    """
    settings = get_settings()
    size = chunk_size or settings.chunk_size
    overlap = settings.chunk_overlap if chunk_overlap is None else chunk_overlap
    chunks = []
    for d in _read_json(pages_path)["documents"]:
        doc = Document(
            d["doc_id"],
            d["source"],
            [
                Page(
                    p["number"],
                    p["text"],
                    images=[Path(img) for img in p.get("images", [])],
                )
                for p in d["pages"]
            ],
        )
        chunks += [
            {"id": c.id, "text": c.text, "metadata": c.metadata}
            for c in chunk_document(doc, size, overlap, include_image_descriptions=True)
        ]
    if not chunks:
        raise ValueError("Aucun passage n'a été produit.")
    payload = {"chunk_size": size, "chunk_overlap": overlap, "chunks": chunks}
    return _write_json(Path(pages_path).parent / "03_chunks.json", payload)


def create_embeddings(chunks_path: str) -> str:
    """4. Embeddings des passages (multilingual-e5-small, préfixe « passage: »)."""
    chunks = _read_json(chunks_path)["chunks"]
    store = VectorStore(client=chromadb.EphemeralClient())  # seul le modèle sert ici, pas la base
    vectors = store._embed([c["text"] for c in chunks], "passage")
    payload = {
        "model": store.settings.embedding_model,
        "dimensions": len(vectors[0]),
        "entries": [{"id": c["id"], "vector": v} for c, v in zip(chunks, vectors, strict=True)],
    }
    return _write_json(Path(chunks_path).parent / "04_embeddings.json", payload)


def index_vectors(embeddings_path: str, chunks_path: str) -> str:
    """5. Base ChromaDB (cosinus) propre au run, à partir des embeddings déjà calculés.
    L'index BM25 de la recherche hybride est reconstruit à la volée depuis cette base."""
    run_dir = Path(embeddings_path).parent
    embeddings = _read_json(embeddings_path)
    chunks = {c["id"]: c for c in _read_json(chunks_path)["chunks"]}
    store = VectorStore(get_settings().model_copy(update={"chroma_dir": run_dir / "chroma", "collection": COLLECTION}))
    entries = embeddings["entries"]
    for i in range(0, len(entries), 64):
        batch = entries[i : i + 64]
        store.collection.upsert(
            ids=[e["id"] for e in batch],
            documents=[chunks[e["id"]]["text"] for e in batch],
            metadatas=[chunks[e["id"]]["metadata"] for e in batch],
            embeddings=[e["vector"] for e in batch],
        )
    index = {
        "engine": "chromadb + bm25",
        "distance": "cosine",
        "search_mode": store.settings.search_mode,
        "embedding_model": embeddings["model"],
        "dimensions": embeddings["dimensions"],
        "chroma_dir": str((run_dir / "chroma").resolve()),
        "collection": COLLECTION,
        "count": store.collection.count(),
        "documents": store.documents(),
        "is_simulated": False,
    }
    return _write_json(run_dir / "05_vector_index.json", index)


def generate_quiz(
    chunks_path: str,
    index_path: str,
    n: int = 5,
    difficulty: str = "moyen",
    reading_level: str = "standard",
    max_pages: int = 5,
    llm: LLM | None = None,
) -> str:
    """6. Un quiz par document, sur ses `max_pages` premières pages (Tutor.quiz : LLM + JSON vérifié).
    `llm` permet de passer un faux LLM dans les tests."""
    store = _store(index_path)
    llm = llm or LLM()
    tutor = Tutor(store=store, llm=llm)
    chunks = _read_json(chunks_path)["chunks"]
    quizzes = []
    for doc_id, source in store.documents().items():
        pages = sorted({c["metadata"]["page"] for c in chunks if c["metadata"]["doc_id"] == doc_id})[:max_pages]
        quiz = tutor.quiz(doc_id=doc_id, pages=pages, n=n, difficulty=difficulty, reading_level=reading_level)
        quizzes.append({"doc_id": doc_id, "source": source, "pages": pages, "items": quiz.model_dump()["items"]})
    payload = {
        "generator": llm.model,
        "prompts": [load_prompt("quiz").tag, styles_tag()],
        "reading_level": reading_level,
        "difficulty": difficulty,
        "quizzes": quizzes,
        "is_simulated": False,
    }
    return _write_json(Path(chunks_path).parent / "06_quiz.json", payload)


def evaluate_quiz(quiz_path: str, chunks_path: str, index_path: str, reference_path: str | None = None) -> str:
    """7. Évaluation sans LLM (rapide, sans quota) :
    - source_page_rate : part des questions dont les pages citées sont bien des pages du quiz ;
    - retrieval_hit_at_5 / mrr : recherche hybride sur le jeu de référence (reference.jsonl),
      limité aux cours présents dans l'index ; ignoré si aucun jeu n'est fourni.
    quality_score = moyenne des scores disponibles parmi source_page_rate et retrieval_hit_at_5.
    La fidélité (LLM juge) reste mesurée par `tuteur eval` : trop d'appels pour un batch."""
    quiz = _read_json(quiz_path)
    chunks = _read_json(chunks_path)["chunks"]
    items = [(q, item) for q in quiz["quizzes"] for item in q["items"]]
    linked = [bool(item["source_pages"]) and set(item["source_pages"]) <= set(q["pages"]) for q, item in items]
    metrics: dict[str, Any] = {
        "document_count": len(quiz["quizzes"]),
        "chunk_count": len(chunks),
        "quiz_question_count": len(items),
        "source_page_rate": _score(statistics.mean(linked)) if linked else 0.0,
    }

    refs = []
    if reference_path and Path(reference_path).exists():
        sources = set(_read_json(index_path)["documents"].values())
        lines = Path(reference_path).read_text(encoding="utf-8").splitlines()
        refs = [r for r in map(json.loads, filter(str.strip, lines))
                if r.get("source") in sources and r.get("evidence")]
    if refs:
        # import local : evaluation tire des dépendances lourdes
        from tuteur.evaluation import retrieval_metrics

        retrieval = retrieval_metrics(_store(index_path), refs, k=5)
        metrics |= {"retrieval_question_count": len(refs), "retrieval_hit_at_1": _score(retrieval["hit@1"]),
                    "retrieval_hit_at_5": _score(retrieval["hit@5"]), "retrieval_mrr": _score(retrieval["mrr"])}

    scores = [metrics["source_page_rate"]] + ([metrics["retrieval_hit_at_5"]] if refs else [])
    metrics["quality_score"] = _score(statistics.mean(scores))
    metrics["is_synthetic_evaluation"] = False
    return _write_json(Path(quiz_path).parent / "07_evaluation.json", metrics)


def log_rag_run(
    root: str | Path,
    run_id: str,
    evaluation_path: str,
    quiz_path: str,
    index_path: str,
    tracking_uri: str,
    experiment_name: str,
) -> str:
    """8–9. Enregistre le run dans MLflow puis écrit registry/rag/latest.json
    (même format que le manifeste simulé, `is_simulated` à false)."""
    import mlflow  # dépendance de l'orchestration, pas du tuteur : importée seulement ici

    metrics = _read_json(evaluation_path)
    quiz = _read_json(quiz_path)
    index = _read_json(index_path)
    run_dir = Path(evaluation_path).parent
    params = {
        "embedding_model": index["embedding_model"],
        "vector_index": index["engine"],
        "search_mode": index["search_mode"],
        "chunk_size": _read_json(run_dir / "03_chunks.json")["chunk_size"],
        "chunk_overlap": _read_json(run_dir / "03_chunks.json")["chunk_overlap"],
        "quiz_generator": quiz["generator"],
        "prompts": ",".join(quiz["prompts"]),
        "reading_level": quiz["reading_level"],
    }
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name=f"rag-{run_id}") as active_run:
        mlflow.set_tags({"pipeline": "rag_pipeline", "data_kind": "course", "model_kind": "real"})
        mlflow.log_params(params)
        mlflow.log_metrics({k: float(v) for k, v in metrics.items() if isinstance(v, int | float) and not isinstance(v, bool)})
        mlflow.log_artifacts(str(run_dir), artifact_path="rag_pipeline")
        mlflow_run_id = active_run.info.run_id

    manifest = {
        "pipeline": "rag_pipeline",
        "airflow_run_id": run_id,
        "version": _version({"quiz": quiz["quizzes"], "index": params}),
        "created_at": datetime.now(UTC).isoformat(),
        "status": "produced",
        "validated": None,
        "mlflow_run_id": mlflow_run_id,
        "params": params,
        "artifacts": {
            "quiz": str(Path(quiz_path).resolve()),
            "vector_index": str(Path(index_path).resolve()),
            "evaluation": str(Path(evaluation_path).resolve()),
        },
        "metrics": metrics,
        "is_simulated": False,
    }
    return _write_json(Path(root) / "registry" / "rag" / "latest.json", manifest)
