"""Tests d'intégration légers des endpoints FastAPI."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["mode"] == "simulation"


def test_swagger_ui_is_available() -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "swagger-ui" in response.text.lower()


def test_prometheus_metrics_are_available() -> None:
    client.get("/health")
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds_bucket" in response.text
    assert 'endpoint="/health"' in response.text


def test_validated_artifacts_is_non_blocking_without_batch_run(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VALIDATION_MANIFEST_PATH", str(tmp_path / "missing.json"))
    response = client.get("/artifacts/validated")

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["is_simulated"] is True


def test_generate_quiz() -> None:
    response = client.post(
        "/generate-quiz",
        json={
            "subject": "Mathématiques",
            "topic": "Fractions",
            "difficulty": "facile",
            "number_of_questions": 2,
            "accessibility_needs": ["lecture simplifiée"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_simulated"] is True
    assert len(body["questions"]) == 2
    assert body["questions"][0]["correct_answer"] == "Choix A"
    assert "lecture simplifiée" in body["accessibility_support"][0]


def test_generate_quiz_rejects_invalid_question_count() -> None:
    response = client.post(
        "/generate-quiz",
        json={
            "subject": "Mathématiques",
            "topic": "Fractions",
            "number_of_questions": 0,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "number_of_questions"


def test_student_answer_correct() -> None:
    response = client.post(
        "/student-answer",
        json={
            "quiz_id": "quiz-demo",
            "question_id": 1,
            "answer": " Choix A ",
            "expected_answer": "choix a",
        },
    )

    assert response.status_code == 200
    assert response.json()["is_correct"] is True
    assert response.json()["score"] == 1.0


def test_student_answer_rejects_missing_expected_answer() -> None:
    response = client.post(
        "/student-answer",
        json={"quiz_id": "quiz-demo", "question_id": 1, "answer": "Choix A"},
    )

    assert response.status_code == 422


def test_next_activity_uses_remediation_rule() -> None:
    response = client.post(
        "/next-activity",
        json={
            "performance_score": 0.35,
            "attempts": 3,
            "current_topic": "Fractions",
            "accessibility_needs": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["activity_type"] == "remediation"
    assert response.json()["policy"] == "mock-rules-v1"


def test_next_activity_rejects_score_above_one() -> None:
    response = client.post(
        "/next-activity",
        json={"performance_score": 1.2, "attempts": 1, "current_topic": "Fractions"},
    )

    assert response.status_code == 422


def test_unknown_fields_are_rejected() -> None:
    response = client.post(
        "/generate-quiz",
        json={
            "subject": "Mathématiques",
            "topic": "Fractions",
            "unexpected": "value",
        },
    )

    assert response.status_code == 422
