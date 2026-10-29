"""Lecture en seule consultation du manifeste produit par les pipelines batch."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def get_validated_artifacts() -> dict[str, Any]:
    """Retourne le dernier manifeste sans lancer de traitement Airflow."""
    manifest_path = Path(
        os.getenv(
            "VALIDATION_MANIFEST_PATH",
            "/app/shared/registry/validation/latest.json",
        )
    )
    if not manifest_path.exists():
        return {
            "status": "unavailable",
            "message": "Aucun manifeste de validation batch n'est encore disponible.",
            "artifacts": {},
            "is_simulated": True,
        }
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"status": "available", **payload}
