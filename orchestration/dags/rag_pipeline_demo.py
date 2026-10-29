"""DAG batch préparant les futurs traitements RAG avec des mocks déterministes."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from airflow.sdk import dag, get_current_context, task
from tuteur_pipelines import rag_pipeline

DEFAULT_ARGS = {
    "owner": "mlops",
    "retries": 2,
    "retry_delay": timedelta(seconds=20),
    "execution_timeout": timedelta(minutes=5),
}


def _runtime() -> tuple[str, str]:
    context = get_current_context()
    return os.environ["PIPELINE_SHARED_DIR"], str(context["run_id"])


@dag(
    dag_id="rag_pipeline_demo",
    description="Pipeline RAG batch simulé, sans document ni modèle réel.",
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["demo", "rag", "synthetic"],
)
def build_rag_pipeline():
    @task
    def load_course() -> str:
        root, run_id = _runtime()
        return rag_pipeline.load_synthetic_course(root, run_id)

    @task
    def clean_content(source_path: str) -> str:
        return rag_pipeline.extract_and_clean(source_path)

    @task
    def chunk_content(cleaned_path: str) -> str:
        return rag_pipeline.split_into_chunks(cleaned_path)

    @task
    def create_embeddings(chunks_path: str) -> str:
        return rag_pipeline.simulate_embeddings(chunks_path)

    @task
    def index_vectors(embeddings_path: str) -> str:
        return rag_pipeline.simulate_vector_index(embeddings_path)

    @task
    def generate_quiz(chunks_path: str, index_path: str) -> str:
        return rag_pipeline.generate_mock_quiz(chunks_path, index_path)

    @task
    def evaluate_quiz(quiz_path: str, chunks_path: str) -> str:
        return rag_pipeline.evaluate_mock_quiz(quiz_path, chunks_path)

    @task
    def register_in_mlflow(evaluation_path: str, quiz_path: str, index_path: str) -> str:
        root, run_id = _runtime()
        return rag_pipeline.log_rag_run(
            root,
            run_id,
            evaluation_path,
            quiz_path,
            index_path,
            os.environ["MLFLOW_TRACKING_URI"],
            os.environ["MLFLOW_EXPERIMENT_NAME"],
        )

    source = load_course()
    cleaned = clean_content(source)
    chunks = chunk_content(cleaned)
    embeddings = create_embeddings(chunks)
    index = index_vectors(embeddings)
    quiz = generate_quiz(chunks, index)
    evaluation = evaluate_quiz(quiz, chunks)
    register_in_mlflow(evaluation, quiz, index)


build_rag_pipeline()
