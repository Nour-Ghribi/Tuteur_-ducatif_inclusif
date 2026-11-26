"""Vérifie que les runs, métriques, artefacts et traces de démonstration existent."""

import argparse
import os
import sys

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import mlflow  # noqa: E402
from mlflow import MlflowClient  # noqa: E402

EXPERIMENT_NAME = "tuteur-inclusif-demo"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tracking-uri",
        default=os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"),
    )
    return parser.parse_args()


def verify(tracking_uri: str) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient()
    experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
    if experiment is None:
        raise RuntimeError(f"Expérience absente : {EXPERIMENT_NAME}")

    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        order_by=["attributes.start_time DESC"],
    )
    traces = mlflow.search_traces(
        locations=[experiment.experiment_id],
        return_type="list",
        include_spans=True,
    )

    required_params = {"model_name", "prompt_version", "temperature", "max_tokens"}
    required_metrics = {"response_time_ms", "synthetic_quality_score"}
    required_tags = {"data_classification", "evaluation_status", "component"}
    complete_runs = [
        run
        for run in runs
        if required_params <= run.data.params.keys()
        and required_metrics <= run.data.metrics.keys()
        and required_tags <= run.data.tags.keys()
    ]
    runs_with_artifact = [
        run
        for run in runs
        if any(item.path == "simulation_result.json" for item in client.list_artifacts(run.info.run_id))
    ]

    if len(complete_runs) < 3:
        raise RuntimeError("Moins de trois runs contiennent les données attendues.")
    if len(runs_with_artifact) < 3:
        raise RuntimeError("Moins de trois runs contiennent l'artefact JSON attendu.")
    if not traces:
        raise RuntimeError("Aucune trace MLflow n'a été trouvée.")

    print(f"Expérience : {experiment.name} (ID={experiment.experiment_id})")
    print(f"Runs totaux : {len(runs)}")
    print(f"Runs complets (paramètres, métriques, tags) : {len(complete_runs)}")
    print(f"Runs avec artefact JSON : {len(runs_with_artifact)}")
    print(f"Traces consultables : {len(traces)}")


if __name__ == "__main__":
    arguments = parse_args()
    verify(arguments.tracking_uri)
