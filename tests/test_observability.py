"""Tests des briques de monitoring de l'étape 7."""

import csv

from app.telemetry import _enabled
from scripts.generate_drift_report import generate_datasets


def test_otel_boolean_configuration() -> None:
    assert _enabled("true") is True
    assert _enabled("ON") is True
    assert _enabled("false") is False
    assert _enabled(None) is False


def test_synthetic_periods_contain_an_intentional_shift(tmp_path) -> None:
    reference_path, current_path = generate_datasets(size=120, data_dir=tmp_path)

    with reference_path.open(encoding="utf-8") as stream:
        reference = list(csv.DictReader(stream))
    with current_path.open(encoding="utf-8") as stream:
        current = list(csv.DictReader(stream))

    reference_duration = sum(float(row["session_duration_minutes"]) for row in reference) / 120
    current_duration = sum(float(row["session_duration_minutes"]) for row in current) / 120
    reference_score = sum(float(row["quiz_score"]) for row in reference) / 120
    current_score = sum(float(row["quiz_score"]) for row in current) / 120

    assert current_duration - reference_duration > 10
    assert reference_score - current_score > 0.1
    assert {row["sample_id"].split("-")[0] for row in reference} == {"reference"}
    assert {row["sample_id"].split("-")[0] for row in current} == {"current"}
