"""DAG batch simulant la préparation et l'évaluation d'une politique RL."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from airflow.sdk import dag, get_current_context, task
from tuteur_pipelines import rl_pipeline

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
    dag_id="rl_pipeline_demo",
    description="Pipeline RL batch simulé, sans apprentissage ni données réelles.",
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["demo", "rl", "synthetic"],
)
def build_rl_pipeline():
    @task
    def load_interactions() -> str:
        root, run_id = _runtime()
        return rl_pipeline.load_synthetic_interactions(root, run_id)

    @task
    def preprocess(interactions_path: str) -> str:
        return rl_pipeline.preprocess_interactions(interactions_path)

    @task
    def prepare_samples(preprocessed_path: str) -> str:
        return rl_pipeline.prepare_observations_and_rewards(preprocessed_path)

    @task
    def train_policy(samples_path: str) -> str:
        return rl_pipeline.simulate_policy_training(samples_path)

    @task
    def evaluate_policy(policy_path: str, samples_path: str) -> str:
        return rl_pipeline.evaluate_mock_policy(policy_path, samples_path)

    @task
    def register_in_mlflow(evaluation_path: str, policy_path: str) -> dict[str, str]:
        _, run_id = _runtime()
        return rl_pipeline.log_rl_run(
            evaluation_path,
            policy_path,
            run_id,
            os.environ["MLFLOW_TRACKING_URI"],
            os.environ["MLFLOW_EXPERIMENT_NAME"],
        )

    @task
    def publish_policy(
        policy_path: str, evaluation_path: str, mlflow_info: dict[str, str]
    ) -> str:
        root, run_id = _runtime()
        return rl_pipeline.publish_policy_version(
            root, run_id, policy_path, evaluation_path, mlflow_info
        )

    interactions = load_interactions()
    processed = preprocess(interactions)
    samples = prepare_samples(processed)
    policy = train_policy(samples)
    evaluation = evaluate_policy(policy, samples)
    mlflow_info = register_in_mlflow(evaluation, policy)
    publish_policy(policy, evaluation, mlflow_info)


build_rl_pipeline()
