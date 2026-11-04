"""Pipeline batch de bout en bout (vrai cours, vrais embeddings, ChromaDB sur disque),
avec un LLM et un MLflow simulés : aucun appel réseau."""

import json
import shutil
import sys
import types
from pathlib import Path

import pytest

from tuteur import pipeline
from tuteur.llm import LLM

ROOT = Path(__file__).parents[1]


class FakeLLM(LLM):
    def __init__(self):
        self.model = "fake-llm"

    def chat(self, system, user, json_mode=False):
        item = dict(type="vrai_faux", question="La chlorophylle est verte.", choices=["Vrai", "Faux"],
                    answer="Vrai", explanation="Elle réfléchit le vert.", difficulty="facile",
                    competence="chlorophylle", source_pages=[1])
        return json.dumps({"items": [item]})


@pytest.fixture
def fake_mlflow(monkeypatch):
    logged = {}
    run = types.SimpleNamespace(info=types.SimpleNamespace(run_id="run-123"))

    class _Run:
        def __enter__(self):
            return run

        def __exit__(self, *exc):
            return False

    module = types.SimpleNamespace(
        set_tracking_uri=lambda uri: logged.update(uri=uri),
        set_experiment=lambda name: logged.update(experiment=name),
        start_run=lambda run_name: _Run(),
        set_tags=lambda tags: logged.update(tags=tags),
        log_params=lambda params: logged.update(params=params),
        log_metrics=lambda metrics: logged.update(metrics=metrics),
        log_artifacts=lambda path, artifact_path: logged.update(artifacts=path),
    )
    monkeypatch.setitem(sys.modules, "mlflow", module)
    return logged


def test_full_pipeline_writes_real_manifest(tmp_path, fake_mlflow):
    (tmp_path / "inputs").mkdir()
    shutil.copy(ROOT / "data" / "raw" / "photosynthese.md", tmp_path / "inputs")
    shutil.copy(ROOT / "eval" / "reference.jsonl", tmp_path / "inputs")  # ignoré comme cours (.jsonl)

    sources = pipeline.load_course(tmp_path, "manual__2026-11-04T10:00:00")
    pages = pipeline.extract_and_clean(sources)
    chunks = pipeline.split_into_chunks(pages)
    embeddings = pipeline.create_embeddings(chunks)
    index = pipeline.index_vectors(embeddings, chunks)
    quiz = pipeline.generate_quiz(chunks, index, n=1, llm=FakeLLM())
    evaluation = pipeline.evaluate_quiz(quiz, chunks, index, reference_path=str(tmp_path / "inputs" / "reference.jsonl"))
    manifest_path = pipeline.log_rag_run(tmp_path, "manual__2026-11-04T10:00:00", evaluation, quiz, index,
                                         "http://mlflow:5000", "tuteur-test")

    assert len(json.loads(Path(sources).read_text(encoding="utf-8"))["files"]) == 1
    assert Path(sources).parent.name == "manual__2026-11-04T10_00_00"  # run_id rendu portable

    idx = json.loads(Path(index).read_text(encoding="utf-8"))
    assert idx["count"] == len(json.loads(Path(chunks).read_text(encoding="utf-8"))["chunks"]) >= 2
    assert idx["dimensions"] == 384 and idx["is_simulated"] is False

    metrics = json.loads(Path(evaluation).read_text(encoding="utf-8"))
    assert metrics["source_page_rate"] == 1.0
    assert metrics["retrieval_question_count"] == 10  # les questions sur le PDF sont écartées
    assert 0.0 <= metrics["retrieval_hit_at_5"] <= 1.0
    assert metrics["quality_score"] == round((1.0 + metrics["retrieval_hit_at_5"]) / 2, 4)

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    assert Path(manifest_path) == tmp_path / "registry" / "rag" / "latest.json"
    assert manifest["is_simulated"] is False and manifest["mlflow_run_id"] == "run-123"
    assert all(Path(p).exists() for p in manifest["artifacts"].values())  # vérifié par l'évaluation mlops
    assert manifest["version"].startswith("rag-")
    assert fake_mlflow["params"]["chunk_size"] == 800
    assert "is_synthetic_evaluation" not in fake_mlflow["metrics"]  # les booléens ne sont pas des métriques


def test_load_course_without_inputs_fails_clearly(tmp_path):
    (tmp_path / "inputs").mkdir()
    with pytest.raises(FileNotFoundError, match="Aucun cours"):
        pipeline.load_course(tmp_path, "manual")
