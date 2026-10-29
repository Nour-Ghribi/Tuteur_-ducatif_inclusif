"""Garde-fous simples pour le catalogue pédagogique synthétique."""

import csv
from pathlib import Path

DATASET_PATH = Path("data/raw/course_catalog.csv")
FORBIDDEN_PERSONAL_FIELDS = {
    "student_name",
    "student_id",
    "email",
    "phone",
    "address",
    "date_of_birth",
}


def test_course_catalog_contains_only_synthetic_rows() -> None:
    with DATASET_PATH.open(encoding="utf-8", newline="") as dataset:
        rows = list(csv.DictReader(dataset))

    assert rows
    assert all(row["is_synthetic"].casefold() == "true" for row in rows)


def test_course_catalog_has_no_personal_identity_fields() -> None:
    with DATASET_PATH.open(encoding="utf-8", newline="") as dataset:
        fieldnames = set(csv.DictReader(dataset).fieldnames or [])

    assert fieldnames.isdisjoint(FORBIDDEN_PERSONAL_FIELDS)
