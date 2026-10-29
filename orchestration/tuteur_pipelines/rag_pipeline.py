"""Implémentation modulaire et entièrement synthétique du pipeline RAG."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .common import (
    content_version,
    read_json,
    run_directory,
    utc_timestamp,
    write_json,
    write_latest_manifest,
)


def load_synthetic_course(root: str | Path, run_id: str) -> str:
    source = Path(root) / "inputs" / "course_demo.txt"
    if not source.exists():
        raise FileNotFoundError(f"Cours synthétique introuvable : {source}")
    destination = run_directory(root, "rag", run_id) / "01_source.txt"
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return str(destination)


def extract_and_clean(source_path: str) -> str:
    source = Path(source_path)
    text = source.read_text(encoding="utf-8")
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) < 100:
        raise ValueError("Le cours synthétique est trop court pour la démonstration RAG.")
    destination = source.parent / "02_cleaned.txt"
    destination.write_text(cleaned, encoding="utf-8")
    return str(destination)


def split_into_chunks(cleaned_path: str, chunk_size: int = 320) -> str:
    source = Path(cleaned_path)
    text = source.read_text(encoding="utf-8")
    words = text.split()
    chunks: list[dict[str, Any]] = []
    current: list[str] = []
    current_size = 0
    for word in words:
        projected = current_size + len(word) + (1 if current else 0)
        if current and projected > chunk_size:
            chunks.append({"chunk_id": len(chunks) + 1, "text": " ".join(current)})
            current = []
            current_size = 0
        current.append(word)
        current_size += len(word) + (1 if current_size else 0)
    if current:
        chunks.append({"chunk_id": len(chunks) + 1, "text": " ".join(current)})
    if not chunks:
        raise ValueError("Aucun chunk n'a été produit.")
    return str(write_json(source.parent / "03_chunks.json", chunks))


def simulate_embeddings(chunks_path: str, dimensions: int = 12) -> str:
    source = Path(chunks_path)
    chunks = read_json(source)
    embeddings = []
    for chunk in chunks:
        digest = hashlib.sha256(chunk["text"].encode("utf-8")).digest()
        vector = [round(digest[index] / 255, 6) for index in range(dimensions)]
        embeddings.append({"chunk_id": chunk["chunk_id"], "vector": vector})
    return str(write_json(source.parent / "04_embeddings.json", embeddings))


def simulate_vector_index(embeddings_path: str) -> str:
    source = Path(embeddings_path)
    embeddings = read_json(source)
    index = {
        "engine": "mock-vector-index",
        "distance": "cosine-simulated",
        "dimensions": len(embeddings[0]["vector"]),
        "entries": embeddings,
        "is_simulated": True,
    }
    return str(write_json(source.parent / "05_vector_index.json", index))


def generate_mock_quiz(chunks_path: str, index_path: str) -> str:
    chunks = read_json(chunks_path)
    index = read_json(index_path)
    questions = []
    for position, chunk in enumerate(chunks[:3], start=1):
        excerpt = chunk["text"][:90].rstrip(" ,.;:")
        questions.append(
            {
                "question_id": position,
                "prompt": f"Explique avec tes mots l'idée suivante : {excerpt}…",
                "expected_keywords": chunk["text"].lower().split()[:4],
                "source_chunk_id": chunk["chunk_id"],
            }
        )
    quiz = {
        "generator": "mock-rag-quiz-v1",
        "index_engine": index["engine"],
        "questions": questions,
        "is_simulated": True,
    }
    return str(write_json(Path(chunks_path).parent / "06_quiz.json", quiz))


def evaluate_mock_quiz(quiz_path: str, chunks_path: str) -> str:
    quiz = read_json(quiz_path)
    chunks = read_json(chunks_path)
    question_count = len(quiz["questions"])
    linked_count = sum(bool(item["source_chunk_id"]) for item in quiz["questions"])
    quality_score = round((linked_count / max(question_count, 1)) * 0.9, 4)
    metrics = {
        "chunk_count": len(chunks),
        "quiz_question_count": question_count,
        "source_link_rate": round(linked_count / max(question_count, 1), 4),
        "synthetic_quality_score": quality_score,
        "is_synthetic_evaluation": True,
    }
    return str(write_json(Path(quiz_path).parent / "07_evaluation.json", metrics))


def log_rag_run(
    root: str | Path,
    run_id: str,
    evaluation_path: str,
    quiz_path: str,
    index_path: str,
    tracking_uri: str,
    experiment_name: str,
) -> str:
    import mlflow

    metrics = read_json(evaluation_path)
    run_dir = Path(evaluation_path).parent
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name=f"rag-{run_id}") as active_run:
        mlflow.set_tags(
            {
                "pipeline": "rag_pipeline_demo",
                "data_kind": "synthetic",
                "model_kind": "mock",
            }
        )
        mlflow.log_params(
            {
                "embedding_model": "sha256-mock-v1",
                "vector_index": "mock-vector-index",
                "quiz_generator": "mock-rag-quiz-v1",
            }
        )
        mlflow.log_metrics(
            {key: float(value) for key, value in metrics.items() if isinstance(value, int | float)}
        )
        mlflow.log_artifacts(str(run_dir), artifact_path="rag_pipeline")
        mlflow_run_id = active_run.info.run_id

    version = content_version("rag", {"quiz": read_json(quiz_path), "index": read_json(index_path)})
    manifest = {
        "pipeline": "rag_pipeline_demo",
        "airflow_run_id": run_id,
        "version": version,
        "created_at": utc_timestamp(),
        "status": "produced",
        "validated": None,
        "mlflow_run_id": mlflow_run_id,
        "artifacts": {
            "quiz": str(Path(quiz_path).resolve()),
            "vector_index": str(Path(index_path).resolve()),
            "evaluation": str(Path(evaluation_path).resolve()),
        },
        "metrics": metrics,
        "is_simulated": True,
    }
    return str(write_latest_manifest(root, "rag", manifest))
