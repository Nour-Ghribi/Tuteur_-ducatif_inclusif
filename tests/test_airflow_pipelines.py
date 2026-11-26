import json
from pathlib import Path

from orchestration.tuteur_pipelines import evaluation_pipeline, rag_pipeline, rl_pipeline


def _create_inputs(root: Path) -> None:
    inputs = root / "inputs"
    inputs.mkdir()
    (inputs / "course_demo.txt").write_text(
        " ".join(
            [
                "Une fraction représente une partie d'un tout et permet de comparer des quantités."
            ]
            * 8
        ),
        encoding="utf-8",
    )
    (inputs / "student_interactions_demo.json").write_text(
        json.dumps(
            [
                {"interaction_id": "s1", "score": 0.4, "attempts": 2, "difficulty": "moyen"},
                {"interaction_id": "s2", "score": 0.9, "attempts": 1, "difficulty": "difficile"},
            ]
        ),
        encoding="utf-8",
    )


def test_rag_pipeline_pure_functions(tmp_path: Path) -> None:
    _create_inputs(tmp_path)
    source = rag_pipeline.load_synthetic_course(tmp_path, "manual__rag-test")
    cleaned = rag_pipeline.extract_and_clean(source)
    chunks = rag_pipeline.split_into_chunks(cleaned, chunk_size=150)
    embeddings = rag_pipeline.simulate_embeddings(chunks)
    index = rag_pipeline.simulate_vector_index(embeddings)
    quiz = rag_pipeline.generate_mock_quiz(chunks, index)
    evaluation = rag_pipeline.evaluate_mock_quiz(quiz, chunks)

    metrics = json.loads(Path(evaluation).read_text(encoding="utf-8"))
    assert metrics["chunk_count"] >= 2
    assert metrics["quiz_question_count"] >= 1
    assert metrics["is_synthetic_evaluation"] is True


def test_rl_pipeline_pure_functions(tmp_path: Path) -> None:
    _create_inputs(tmp_path)
    interactions = rl_pipeline.load_synthetic_interactions(tmp_path, "manual__rl-test")
    processed = rl_pipeline.preprocess_interactions(interactions)
    samples = rl_pipeline.prepare_observations_and_rewards(processed)
    policy = rl_pipeline.simulate_policy_training(samples)
    evaluation = rl_pipeline.evaluate_mock_policy(policy, samples)

    metrics = json.loads(Path(evaluation).read_text(encoding="utf-8"))
    assert metrics["sample_count"] == 2
    assert 0 <= metrics["synthetic_policy_score"] <= 1
    assert metrics["is_synthetic_evaluation"] is True


def test_evaluation_refuses_missing_artifacts(tmp_path: Path) -> None:
    refs = evaluation_pipeline.collect_latest_artifacts(tmp_path, "manual__evaluation-test")
    checks = evaluation_pipeline.verify_artifact_versions(refs)
    results = evaluation_pipeline.verify_evaluation_results(refs, checks)
    decision = evaluation_pipeline.compare_with_thresholds(results, 0.75, 0.45)
    report = evaluation_pipeline.generate_validation_report(decision)

    payload = json.loads(Path(decision).read_text(encoding="utf-8"))
    assert payload["overall"]["accepted"] is False
    assert "REFUSÉ" in Path(report).read_text(encoding="utf-8")
