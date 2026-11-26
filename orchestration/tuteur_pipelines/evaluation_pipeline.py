"""Validation croisée des derniers artefacts RAG et RL simulés."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    read_json,
    run_directory,
    utc_timestamp,
    write_json,
)

PIPELINES = ("rag", "rl")


def collect_latest_artifacts(root: str | Path, run_id: str) -> str:
    refs: dict[str, Any] = {}
    for pipeline in PIPELINES:
        manifest_path = Path(root) / "registry" / pipeline / "latest.json"
        refs[pipeline] = {
            "available": manifest_path.exists(),
            "manifest_path": str(manifest_path.resolve()),
            "manifest": read_json(manifest_path) if manifest_path.exists() else None,
        }
    destination = run_directory(root, "evaluation", run_id) / "01_artifact_refs.json"
    return str(write_json(destination, refs))


def verify_artifact_versions(refs_path: str) -> str:
    refs = read_json(refs_path)
    checks = {}
    for pipeline, ref in refs.items():
        manifest = ref.get("manifest") or {}
        artifact_paths = list((manifest.get("artifacts") or {}).values())
        checks[pipeline] = {
            "available": bool(ref["available"]),
            "version": manifest.get("version"),
            "all_files_exist": bool(artifact_paths)
            and all(Path(path).exists() for path in artifact_paths),
        }
    return str(write_json(Path(refs_path).parent / "02_version_checks.json", checks))


def verify_evaluation_results(refs_path: str, checks_path: str) -> str:
    refs = read_json(refs_path)
    checks = read_json(checks_path)
    results = {}
    for pipeline in PIPELINES:
        manifest = (refs[pipeline].get("manifest") or {})
        metrics = manifest.get("metrics") or {}
        score_key = "synthetic_quality_score" if pipeline == "rag" else "synthetic_policy_score"
        results[pipeline] = {
            **checks[pipeline],
            "score_name": score_key,
            "score": metrics.get(score_key),
            "evaluation_is_synthetic": metrics.get("is_synthetic_evaluation") is True,
        }
    return str(write_json(Path(refs_path).parent / "03_evaluation_checks.json", results))


def compare_with_thresholds(results_path: str, rag_threshold: float, rl_threshold: float) -> str:
    results = read_json(results_path)
    thresholds = {"rag": rag_threshold, "rl": rl_threshold}
    decisions = {}
    for pipeline in PIPELINES:
        result = results[pipeline]
        score = result.get("score")
        accepted = bool(
            result["available"]
            and result["all_files_exist"]
            and result["evaluation_is_synthetic"]
            and isinstance(score, int | float)
            and score >= thresholds[pipeline]
        )
        decisions[pipeline] = {
            "accepted": accepted,
            "score": score,
            "threshold": thresholds[pipeline],
            "version": result.get("version"),
        }
    decisions["overall"] = {"accepted": all(item["accepted"] for item in decisions.values())}
    return str(write_json(Path(results_path).parent / "04_decision.json", decisions))


def generate_validation_report(decision_path: str) -> str:
    decisions = read_json(decision_path)
    lines = [
        "# Rapport de validation MLOps — démonstration",
        "",
        "Les scores ci-dessous proviennent uniquement de règles et données synthétiques.",
        "",
    ]
    for pipeline in PIPELINES:
        item = decisions[pipeline]
        status = "VALIDÉ" if item["accepted"] else "REFUSÉ"
        lines.append(
            f"- **{pipeline.upper()}** : {status} — score={item['score']}, "
            f"seuil={item['threshold']}, version={item['version']}"
        )
    lines.extend(["", f"Décision globale : **{decisions['overall']['accepted']}**"])
    report_path = Path(decision_path).parent / "05_validation_report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(report_path)


def log_evaluation_run(
    decision_path: str,
    report_path: str,
    run_id: str,
    tracking_uri: str,
    experiment_name: str,
) -> dict[str, str]:
    import mlflow

    decisions = read_json(decision_path)
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name=f"evaluation-{run_id}") as active_run:
        mlflow.set_tags(
            {
                "pipeline": "mlops_evaluation_demo",
                "data_kind": "synthetic",
                "decision": "accepted" if decisions["overall"]["accepted"] else "refused",
            }
        )
        mlflow.log_params(
            {
                "rag_threshold": decisions["rag"]["threshold"],
                "rl_threshold": decisions["rl"]["threshold"],
            }
        )
        mlflow.log_metrics(
            {
                "rag_accepted": float(decisions["rag"]["accepted"]),
                "rl_accepted": float(decisions["rl"]["accepted"]),
                "overall_accepted": float(decisions["overall"]["accepted"]),
            }
        )
        mlflow.log_artifact(decision_path, artifact_path="evaluation")
        mlflow.log_artifact(report_path, artifact_path="evaluation")
        return {"mlflow_run_id": active_run.info.run_id}


def publish_validation_manifest(
    root: str | Path,
    run_id: str,
    decision_path: str,
    report_path: str,
    mlflow_info: dict[str, str],
) -> str:
    decisions = read_json(decision_path)
    manifest = {
        "pipeline": "mlops_evaluation_demo",
        "airflow_run_id": run_id,
        "created_at": utc_timestamp(),
        "overall_status": "validated" if decisions["overall"]["accepted"] else "refused",
        "artifacts": {
            pipeline: {
                "version": decisions[pipeline]["version"],
                "status": "validated" if decisions[pipeline]["accepted"] else "refused",
            }
            for pipeline in PIPELINES
        },
        "report_path": str(Path(report_path).resolve()),
        "mlflow_run_id": mlflow_info["mlflow_run_id"],
        "is_simulated": True,
    }
    destination = Path(root) / "registry" / "validation" / "latest.json"
    return str(write_json(destination, manifest))
