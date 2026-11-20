"""DAG Airflow du vrai pipeline RAG (module GenAI + RAG, package `tuteur`).

À copier dans orchestration/dags/ de la branche mlops : il remplace rag_pipeline_demo.py
avec le même dag_id et les mêmes tâches, donc le DAG d'évaluation n'a pas à changer de
source. Voir docs/INTEGRATION_MLOPS.md (installation du package, variables, correctif
de l'évaluation).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from airflow.sdk import dag, get_current_context, task
from tuteur import pipeline

DEFAULT_ARGS = {
    "owner": "genai-rag",
    "retries": 2,
    "retry_delay": timedelta(seconds=30),
    "execution_timeout": timedelta(minutes=20),  # premier run : téléchargement du modèle d'embedding
}


def _runtime() -> tuple[str, str]:
    context = get_current_context()
    return os.environ["PIPELINE_SHARED_DIR"], str(context["run_id"])


@dag(
    dag_id="rag_pipeline_demo",
    description="Pipeline RAG réel : PyMuPDF, découpage 800/150, e5 + ChromaDB + BM25, quiz LLM.",
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["rag", "genai"],
)
def build_rag_pipeline():
    @task
    def load_course() -> str:
        root, run_id = _runtime()
        return pipeline.load_course(root, run_id)

    @task
    def clean_content(sources_path: str) -> str:
        return pipeline.extract_and_clean(sources_path)

    @task
    def chunk_content(pages_path: str) -> str:
        return pipeline.split_into_chunks(pages_path)

    @task
    def create_embeddings(chunks_path: str) -> str:
        return pipeline.create_embeddings(chunks_path)

    @task
    def index_vectors(embeddings_path: str, chunks_path: str) -> str:
        return pipeline.index_vectors(embeddings_path, chunks_path)

    @task
    def generate_quiz(chunks_path: str, index_path: str) -> str:
        return pipeline.generate_quiz(
            chunks_path,
            index_path,
            n=int(os.getenv("RAG_QUIZ_QUESTIONS", "5")),
            reading_level=os.getenv("RAG_READING_LEVEL", "standard"),
        )

    @task
    def evaluate_quiz(quiz_path: str, chunks_path: str, index_path: str) -> str:
        root, _ = _runtime()
        return pipeline.evaluate_quiz(quiz_path, chunks_path, index_path, f"{root}/inputs/reference.jsonl")

    @task
    def register_in_mlflow(evaluation_path: str, quiz_path: str, index_path: str) -> str:
        root, run_id = _runtime()
        return pipeline.log_rag_run(
            root,
            run_id,
            evaluation_path,
            quiz_path,
            index_path,
            os.environ["MLFLOW_TRACKING_URI"],
            os.environ["MLFLOW_EXPERIMENT_NAME"],
        )

    sources = load_course()
    pages = clean_content(sources)
    chunks = chunk_content(pages)
    embeddings = create_embeddings(chunks)
    index = index_vectors(embeddings, chunks)
    quiz = generate_quiz(chunks, index)
    evaluation = evaluate_quiz(quiz, chunks, index)
    register_in_mlflow(evaluation, quiz, index)


build_rag_pipeline()
