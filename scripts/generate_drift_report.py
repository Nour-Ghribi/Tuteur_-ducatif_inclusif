"""Génère deux périodes synthétiques et un rapport Evidently de data drift."""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "monitoring" / "evidently"
DATA_DIR = OUTPUT_ROOT / "data"
REPORT_DIR = OUTPUT_ROOT / "reports"
REFERENCE_PATH = DATA_DIR / "reference_period.csv"
CURRENT_PATH = DATA_DIR / "current_period.csv"
REPORT_PATH = REPORT_DIR / "data_drift_report.html"
SNAPSHOT_PATH = REPORT_DIR / "data_drift_snapshot.json"
SUMMARY_PATH = REPORT_DIR / "drift_summary.json"

NUMERICAL_COLUMNS = ["session_duration_minutes", "quiz_score", "interaction_count"]
CATEGORICAL_COLUMNS = ["difficulty", "accessibility_mode"]
MONITORED_COLUMNS = NUMERICAL_COLUMNS + CATEGORICAL_COLUMNS
FIELDNAMES = ["sample_id", *MONITORED_COLUMNS]


def _pick(rng: random.Random, weights: list[tuple[str, float]]) -> str:
    marker = rng.random()
    cumulative = 0.0
    for value, weight in weights:
        cumulative += weight
        if marker <= cumulative:
            return value
    return weights[-1][0]


def _build_rows(period: str, size: int = 240) -> list[dict[str, str | int | float]]:
    rng = random.Random(20261019 if period == "reference" else 20261119)
    shifted = period == "current"
    rows = []
    for index in range(size):
        rows.append(
            {
                "sample_id": f"{period}-{index:04d}",
                "session_duration_minutes": round(
                    max(5.0, rng.gauss(46.0 if shifted else 30.0, 7.0)), 2
                ),
                "quiz_score": round(
                    min(1.0, max(0.0, rng.gauss(0.54 if shifted else 0.74, 0.11))), 3
                ),
                "interaction_count": max(
                    1, round(rng.gauss(15.0 if shifted else 9.0, 2.2))
                ),
                "difficulty": _pick(
                    rng,
                    [("facile", 0.62), ("moyen", 0.28), ("difficile", 0.10)]
                    if shifted
                    else [("facile", 0.25), ("moyen", 0.50), ("difficile", 0.25)],
                ),
                "accessibility_mode": _pick(
                    rng,
                    [("standard", 0.54), ("lecture_simplifiee", 0.31), ("audio", 0.15)],
                ),
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def generate_datasets(size: int = 240, data_dir: Path = DATA_DIR) -> tuple[Path, Path]:
    """Crée deux jeux synthétiques déterministes, sans données d'élèves."""
    reference_path = data_dir / REFERENCE_PATH.name
    current_path = data_dir / CURRENT_PATH.name
    _write_csv(reference_path, _build_rows("reference", size))
    _write_csv(current_path, _build_rows("current", size))
    return reference_path, current_path


def _period_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    size = len(rows)
    return {
        "row_count": size,
        "means": {
            column: round(sum(float(row[column]) for row in rows) / size, 4)
            for column in NUMERICAL_COLUMNS
        },
        "category_shares": {
            column: {
                key: round(count / size, 4)
                for key, count in sorted(Counter(str(row[column]) for row in rows).items())
            }
            for column in CATEGORICAL_COLUMNS
        },
    }


def generate_report() -> dict[str, Any]:
    """Exécute DataDriftPreset avec l'API Evidently 0.7.23."""
    import pandas as pd
    from evidently import DataDefinition, Dataset, Report
    from evidently.presets import DataDriftPreset

    reference_rows = _build_rows("reference")
    current_rows = _build_rows("current")
    _write_csv(REFERENCE_PATH, reference_rows)
    _write_csv(CURRENT_PATH, current_rows)

    definition = DataDefinition(
        id_column="sample_id",
        numerical_columns=NUMERICAL_COLUMNS,
        categorical_columns=CATEGORICAL_COLUMNS,
    )
    reference = Dataset.from_pandas(pd.DataFrame(reference_rows), data_definition=definition)
    current = Dataset.from_pandas(pd.DataFrame(current_rows), data_definition=definition)
    report = Report(
        [DataDriftPreset(columns=MONITORED_COLUMNS, drift_share=0.4, include_tests=True)],
        metadata={
            "project": "tuteur-inclusif",
            "data_kind": "synthetic",
            "intentional_shift": True,
        },
        tags=["demo", "synthetic", "data-drift"],
        include_tests=True,
    )
    snapshot = report.run(current, reference, name="synthetic-period-drift")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot.save_html(str(REPORT_PATH))
    snapshot_data = snapshot.dict()
    SNAPSHOT_PATH.write_text(
        json.dumps(snapshot_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    drift_count_metric = next(
        metric
        for metric in snapshot_data["metrics"]
        if metric["config"]["type"].endswith(":DriftedColumnsCount")
    )
    column_results = {}
    for metric in snapshot_data["metrics"]:
        config = metric["config"]
        if not config["type"].endswith(":ValueDrift"):
            continue
        threshold = float(config["threshold"])
        score = float(metric["value"])
        column_results[config["column"]] = {
            "method": config["method"],
            "score": score,
            "threshold": threshold,
            "drift_detected": score < threshold,
        }

    summary = {
        "evidently_version": "0.7.23",
        "is_synthetic": True,
        "intentional_distribution_change": True,
        "monitored_columns": MONITORED_COLUMNS,
        "dataset_drift_share_threshold": 0.4,
        "result": {
            "drifted_columns": int(drift_count_metric["value"]["count"]),
            "drifted_share": drift_count_metric["value"]["share"],
            "dataset_drift_detected": drift_count_metric["value"]["share"] >= 0.4,
            "columns": column_results,
        },
        "reference": _period_statistics(reference_rows),
        "current": _period_statistics(current_rows),
        "report": str(REPORT_PATH.relative_to(ROOT)),
        "snapshot": str(SNAPSHOT_PATH.relative_to(ROOT)),
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    result = generate_report()
    print(json.dumps(result, ensure_ascii=False, indent=2))
