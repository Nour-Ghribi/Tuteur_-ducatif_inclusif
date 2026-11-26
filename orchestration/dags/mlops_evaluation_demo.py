"""DAG manuel validant indépendamment les derniers artefacts RAG et RL."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from airflow.sdk import dag, get_current_context, task
from tuteur_pipelines import evaluation_pipeline

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
    dag_id="mlops_evaluation_demo",
    description="Validation manuelle des derniers artefacts RAG/RL disponibles.",
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["demo", "evaluation", "synthetic"],
)
def build_evaluation_pipeline():
    @task
    def collect_artifacts() -> str:
        root, run_id = _runtime()
        return evaluation_pipeline.collect_latest_artifacts(root, run_id)

    @task
    def verify_versions(refs_path: str) -> str:
        return evaluation_pipeline.verify_artifact_versions(refs_path)

    @task
    def verify_results(refs_path: str, checks_path: str) -> str:
        return evaluation_pipeline.verify_evaluation_results(refs_path, checks_path)

    @task
    def compare_thresholds(results_path: str) -> str:
        return evaluation_pipeline.compare_with_thresholds(
            results_path,
            float(os.getenv("RAG_QUALITY_THRESHOLD", "0.75")),
            float(os.getenv("RL_POLICY_THRESHOLD", "0.45")),
        )

    @task
    def create_report(decision_path: str) -> str:
        return evaluation_pipeline.generate_validation_report(decision_path)

    @task
    def register_in_mlflow(decision_path: str, report_path: str) -> dict[str, str]:
        _, run_id = _runtime()
        return evaluation_pipeline.log_evaluation_run(
            decision_path,
            report_path,
            run_id,
            os.environ["MLFLOW_TRACKING_URI"],
            os.environ["MLFLOW_EXPERIMENT_NAME"],
        )

    @task
    def publish_manifest(
        decision_path: str, report_path: str, mlflow_info: dict[str, str]
    ) -> str:
        root, run_id = _runtime()
        return evaluation_pipeline.publish_validation_manifest(
            root, run_id, decision_path, report_path, mlflow_info
        )

    refs = collect_artifacts()
    versions = verify_versions(refs)
    results = verify_results(refs, versions)
    decision = compare_thresholds(results)
    report = create_report(decision)
    mlflow_info = register_in_mlflow(decision, report)
    publish_manifest(decision, report, mlflow_info)


build_evaluation_pipeline()
