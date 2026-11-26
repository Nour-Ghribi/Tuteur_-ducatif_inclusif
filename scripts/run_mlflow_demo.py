"""Crée des runs et une trace MLflow à partir de données purement synthétiques."""

import argparse
import os
import sys
import time
from typing import Any

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import mlflow

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

EXPERIMENT_NAME = "tuteur-inclusif-demo"

SIMULATIONS: tuple[dict[str, Any], ...] = (
    {
        "model_name": "mock-quiz-generator-small",
        "prompt_version": "v1",
        "temperature": 0.2,
        "max_tokens": 256,
        "synthetic_quality_score": 0.68,
        "delay_seconds": 0.03,
    },
    {
        "model_name": "mock-quiz-generator-small",
        "prompt_version": "v2",
        "temperature": 0.4,
        "max_tokens": 384,
        "synthetic_quality_score": 0.76,
        "delay_seconds": 0.04,
    },
    {
        "model_name": "mock-quiz-generator-large",
        "prompt_version": "v2-accessible",
        "temperature": 0.3,
        "max_tokens": 512,
        "synthetic_quality_score": 0.84,
        "delay_seconds": 0.05,
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tracking-uri",
        default=os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"),
        help="Adresse du serveur MLflow.",
    )
    return parser.parse_args()


@mlflow.trace(
    name="generation_quiz_simulee",
    span_type="CHAIN",
    attributes={"implementation": "mock", "data_classification": "synthetic"},
)
def trace_mock_quiz(topic: str, prompt_version: str) -> dict[str, Any]:
    """Produit une sortie fictive afin de démontrer MLflow Tracing."""
    with mlflow.start_span(name="recuperation_documents_simulee", span_type="RETRIEVER") as span:
        span.set_inputs({"topic": topic})
        documents = ["document-pedagogique-synthetique-01"]
        span.set_outputs({"document_ids": documents})

    with mlflow.start_span(name="appel_llm_simule", span_type="LLM") as span:
        span.set_inputs({"topic": topic, "prompt_version": prompt_version})
        output = {
            "topic": topic,
            "question": "Question entièrement fictive pour la démonstration ?",
            "choices": ["Choix A", "Choix B", "Choix C"],
            "correct_answer": "Choix A",
            "is_simulated": True,
        }
        span.set_outputs(output)

    mlflow.update_current_trace(
        tags={
            "application": "tuteur-inclusif",
            "simulation": "true",
            "prompt_version": prompt_version,
        }
    )
    return output


def run_simulations(tracking_uri: str) -> None:
    mlflow.set_tracking_uri(tracking_uri)
    experiment = mlflow.set_experiment(EXPERIMENT_NAME)

    for index, simulation in enumerate(SIMULATIONS, start=1):
        with mlflow.start_run(run_name=f"simulation-{index}"):
            started_at = time.perf_counter()
            time.sleep(simulation["delay_seconds"])
            elapsed_ms = (time.perf_counter() - started_at) * 1_000

            mlflow.log_params(
                {
                    "model_name": simulation["model_name"],
                    "prompt_version": simulation["prompt_version"],
                    "temperature": simulation["temperature"],
                    "max_tokens": simulation["max_tokens"],
                }
            )
            mlflow.log_metrics(
                {
                    "response_time_ms": elapsed_ms,
                    "synthetic_quality_score": simulation["synthetic_quality_score"],
                }
            )
            mlflow.set_tags(
                {
                    "application": "tuteur-inclusif",
                    "component": "rag-mock",
                    "data_classification": "synthetic",
                    "evaluation_status": "fictional-demo-only",
                }
            )
            mlflow.log_dict(
                {
                    "notice": "Résultat fictif : ne constitue pas une évaluation réelle.",
                    "configuration": simulation,
                    "output": {
                        "topic": "fractions",
                        "generated_questions": 3,
                        "is_simulated": True,
                    },
                },
                "simulation_result.json",
            )

    trace_mock_quiz(topic="fractions", prompt_version="v2-accessible")
    print(f"Expérience créée : {experiment.name} (ID={experiment.experiment_id})")
    print(f"Runs synthétiques créés : {len(SIMULATIONS)}")
    print("Trace synthétique créée : generation_quiz_simulee")


if __name__ == "__main__":
    arguments = parse_args()
    run_simulations(arguments.tracking_uri)
