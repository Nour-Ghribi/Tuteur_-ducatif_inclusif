"""Utilitaires communs pour les artefacts synthétiques des pipelines."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def shared_root() -> Path:
    """Retourne le stockage partagé persistant utilisé par les tâches batch."""
    return Path(os.getenv("PIPELINE_SHARED_DIR", "/opt/airflow/shared"))


def safe_run_id(run_id: str) -> str:
    """Transforme un identifiant Airflow en nom de dossier portable."""
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", run_id).strip("_") or "manual"


def run_directory(root: str | Path, pipeline: str, run_id: str) -> Path:
    path = Path(root) / "runs" / pipeline / safe_run_id(run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: str | Path, payload: Any) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def content_version(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    return f"{prefix}-{digest}"


def write_latest_manifest(root: str | Path, pipeline: str, payload: dict[str, Any]) -> Path:
    manifest = Path(root) / "registry" / pipeline / "latest.json"
    return write_json(manifest, payload)
