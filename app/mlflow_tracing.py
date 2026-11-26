"""Configuration optionnelle de MLflow Tracing pour les appels simulés."""

import os
from collections.abc import Callable
from functools import wraps
from typing import Any


def trace_quiz_generation[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Trace une fonction seulement lorsqu'un serveur MLflow est configuré."""

    @wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
        if not tracking_uri:
            return function(*args, **kwargs)

        import mlflow

        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT_NAME", "tuteur-inclusif-demo"))

        traced_function: Callable[..., Any] = mlflow.trace(
            function,
            name="generation_quiz_simulee",
            span_type="CHAIN",
            attributes={
                "application": "tuteur-inclusif",
                "data_classification": "synthetic",
                "implementation": "mock",
            },
        )
        return traced_function(*args, **kwargs)

    return wrapper
