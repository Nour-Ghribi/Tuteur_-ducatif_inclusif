"""Implémentation modulaire d'un pipeline RL entièrement simulé."""

from __future__ import annotations

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


def load_synthetic_interactions(root: str | Path, run_id: str) -> str:
    source = Path(root) / "inputs" / "student_interactions_demo.json"
    if not source.exists():
        raise FileNotFoundError(f"Interactions synthétiques introuvables : {source}")
    payload = read_json(source)
    destination = run_directory(root, "rl", run_id) / "01_interactions.json"
    return str(write_json(destination, payload))


def preprocess_interactions(interactions_path: str) -> str:
    source = Path(interactions_path)
    interactions = read_json(source)
    processed = []
    for item in interactions:
        attempts = max(int(item["attempts"]), 1)
        score = min(max(float(item["score"]), 0.0), 1.0)
        processed.append(
            {
                **item,
                "score": score,
                "attempts": attempts,
                "error_rate": round(1 - score, 4),
                "effort": round(attempts * (1 - score), 4),
            }
        )
    return str(write_json(source.parent / "02_preprocessed.json", processed))


def prepare_observations_and_rewards(preprocessed_path: str) -> str:
    source = Path(preprocessed_path)
    interactions = read_json(source)
    samples = []
    for item in interactions:
        reward = round((2 * item["score"] - 1) - 0.05 * (item["attempts"] - 1), 4)
        samples.append(
            {
                "observation": {
                    "score": item["score"],
                    "error_rate": item["error_rate"],
                    "difficulty": item["difficulty"],
                },
                "reward": reward,
            }
        )
    return str(write_json(source.parent / "03_observations_rewards.json", samples))


def simulate_policy_training(samples_path: str) -> str:
    source = Path(samples_path)
    samples = read_json(source)
    rewards = [sample["reward"] for sample in samples]
    average_reward = sum(rewards) / max(len(rewards), 1)
    policy: dict[str, Any] = {
        "name": "mock-adaptive-policy",
        "algorithm": "deterministic-threshold-rules",
        "rules": [
            {"max_score": 0.49, "action": "remediation"},
            {"max_score": 0.79, "action": "practice"},
            {"max_score": 1.0, "action": "challenge"},
        ],
        "training_samples": len(samples),
        "training_average_reward": round(average_reward, 4),
        "is_simulated": True,
    }
    return str(write_json(source.parent / "04_policy_draft.json", policy))


def evaluate_mock_policy(policy_path: str, samples_path: str) -> str:
    policy = read_json(policy_path)
    samples = read_json(samples_path)
    positive_rewards = sum(sample["reward"] >= 0 for sample in samples)
    metrics = {
        "sample_count": len(samples),
        "positive_reward_rate": round(positive_rewards / max(len(samples), 1), 4),
        "synthetic_policy_score": round(
            0.6 * (positive_rewards / max(len(samples), 1))
            + 0.4 * max(policy["training_average_reward"], 0),
            4,
        ),
        "is_synthetic_evaluation": True,
    }
    return str(write_json(Path(policy_path).parent / "05_evaluation.json", metrics))


def log_rl_run(
    evaluation_path: str,
    policy_path: str,
    run_id: str,
    tracking_uri: str,
    experiment_name: str,
) -> dict[str, str]:
    import mlflow

    metrics = read_json(evaluation_path)
    policy = read_json(policy_path)
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name=f"rl-{run_id}") as active_run:
        mlflow.set_tags(
            {
                "pipeline": "rl_pipeline_demo",
                "data_kind": "synthetic",
                "model_kind": "mock",
            }
        )
        mlflow.log_params(
            {
                "algorithm": policy["algorithm"],
                "policy_name": policy["name"],
                "training_samples": policy["training_samples"],
            }
        )
        mlflow.log_metrics(
            {key: float(value) for key, value in metrics.items() if isinstance(value, int | float)}
        )
        mlflow.log_artifacts(str(Path(policy_path).parent), artifact_path="rl_pipeline")
        return {"mlflow_run_id": active_run.info.run_id}


def publish_policy_version(
    root: str | Path,
    run_id: str,
    policy_path: str,
    evaluation_path: str,
    mlflow_info: dict[str, str],
) -> str:
    policy = read_json(policy_path)
    metrics = read_json(evaluation_path)
    version = content_version("policy", policy)
    version_path = Path(root) / "policies" / f"{version}.json"
    write_json(version_path, {**policy, "version": version})
    manifest = {
        "pipeline": "rl_pipeline_demo",
        "airflow_run_id": run_id,
        "version": version,
        "created_at": utc_timestamp(),
        "status": "produced",
        "validated": None,
        "mlflow_run_id": mlflow_info["mlflow_run_id"],
        "artifacts": {
            "policy": str(version_path.resolve()),
            "evaluation": str(Path(evaluation_path).resolve()),
        },
        "metrics": metrics,
        "is_simulated": True,
    }
    return str(write_latest_manifest(root, "rl", manifest))
