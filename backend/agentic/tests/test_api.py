"""End-to-end HTTP tests through a test-only FastAPI app mounting the router."""

import pytest

from tutor_agentic.auth import DevTokenAuthenticator, RejectAllAuthenticator, build_authenticator
from tutor_agentic.config import Settings
from tutor_agentic.errors import AuthenticationRequired
from tutor_agentic.integrations.mocks import FaultInjector, MockContentGenerationAdapter

from .conftest import OTHER_STUDENT_TOKEN, STUDENT_TOKEN, TEACHER_TOKEN, auth

EXPERIENCE = {
    "message": "Génère deux questions",
    "course_id": "demo-bio-101",
    "topic": "photosynthèse",
}
REPORT = {"class_id": "class-demo-a", "period_start": "2026-09-01", "period_end": "2026-10-01"}


@pytest.fixture
def client(make_client):
    return make_client()


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code and body["error"]["request_id"]


class TestAuthentication:
    def test_missing_token(self, client):
        response = client.post("/api/v1/tutor/experiences", json=EXPERIENCE)
        assert_error(response, 401, "authentication_required")
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_invalid_token(self, client):
        response = client.post(
            "/api/v1/tutor/experiences", json=EXPERIENCE, headers=auth("forged-token-xxxxxxxxxxxx")
        )
        assert_error(response, 401, "authentication_required")

    def test_role_header_is_ignored(self, client):
        headers = auth(STUDENT_TOKEN) | {"X-User-Role": "teacher"}
        assert_error(
            client.post("/api/v1/teacher/reports", json=REPORT, headers=headers), 403, "forbidden"
        )

    def test_teacher_restricted_to_own_classes(self, client):
        response = client.post(
            "/api/v1/teacher/reports",
            json=REPORT | {"class_id": "class-other"},
            headers=auth(TEACHER_TOKEN),
        )
        assert_error(response, 403, "forbidden")

    def test_dev_stub_refuses_non_dev_environments(self):
        with pytest.raises(RuntimeError):
            DevTokenAuthenticator({}, environment="production")

    def test_no_auth_configured_rejects_everything(self):
        authenticator = build_authenticator(Settings(_env_file=None, environment="test"))
        assert isinstance(authenticator, RejectAllAuthenticator)
        with pytest.raises(AuthenticationRequired):
            authenticator.authenticate("anything")


class TestEndpoints:
    def test_experience(self, client):
        response = client.post(
            "/api/v1/tutor/experiences", json=EXPERIENCE, headers=auth(STUDENT_TOKEN)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["workflow"] == "experience" and body["intent"] == "quiz"
        assert body["ui"]["schema_version"] == "1.0"
        assert body["ui"]["meta"]["simulated"] is True
        assert len(body["ui"]["blocks"][0]["questions"]) == 2
        assert "correct_option_id" not in response.text

    def test_learner_identity_cannot_be_injected(self, client):
        response = client.post(
            "/api/v1/tutor/experiences",
            json=EXPERIENCE | {"student_ref": "someone-else"},
            headers=auth(STUDENT_TOKEN),
        )
        assert response.status_code == 422

    def test_validation_errors(self, client):
        response = client.post(
            "/api/v1/tutor/experiences", json={"course_id": "x"}, headers=auth(STUDENT_TOKEN)
        )
        assert response.status_code == 422

    def test_answer_round_trip(self, client):
        quiz = client.post(
            "/api/v1/tutor/experiences", json=EXPERIENCE, headers=auth(STUDENT_TOKEN)
        ).json()
        question_id = quiz["ui"]["blocks"][0]["questions"][0]["question_id"]
        answer = {"question_id": question_id, "answer": {"selected_option_id": "b"}}

        response = client.post("/api/v1/tutor/answers", json=answer, headers=auth(STUDENT_TOKEN))
        assert response.status_code == 200
        assert response.json()["ui"]["blocks"][0]["type"] == "quiz_feedback"

        other = client.post("/api/v1/tutor/answers", json=answer, headers=auth(OTHER_STUDENT_TOKEN))
        assert_error(other, 404, "not_found")

    def test_unknown_question(self, client):
        answer = {"question_id": "nope", "answer": {"selected_option_id": "a"}}
        response = client.post("/api/v1/tutor/answers", json=answer, headers=auth(STUDENT_TOKEN))
        assert_error(response, 404, "not_found")

    def test_recommendation_and_outcome(self, client):
        response = client.post(
            "/api/v1/tutor/recommendations",
            json={
                "course_id": "demo-bio-101",
                "topic": "photosynthèse",
            },
            headers=auth(STUDENT_TOKEN),
        )
        assert response.status_code == 200
        card = response.json()["ui"]["blocks"][0]
        assert card["type"] == "recommendation_card"

        ack = client.post(
            f"/api/v1/tutor/recommendations/{card['recommendation_id']}/outcome",
            json={"completed": True, "score": 0.7},
            headers=auth(STUDENT_TOKEN),
        )
        assert ack.status_code == 200 and ack.json()["accepted"] is True

    def test_students_cannot_request_reports(self, client):
        response = client.post("/api/v1/teacher/reports", json=REPORT, headers=auth(STUDENT_TOKEN))
        assert_error(response, 403, "forbidden")

    def test_teacher_report(self, client):
        response = client.post("/api/v1/teacher/reports", json=REPORT, headers=auth(TEACHER_TOKEN))
        assert response.status_code == 200
        body = response.json()
        assert body["ui"]["blocks"][0]["type"] == "metric_grid"
        assert body["ui"]["meta"]["simulated"] is True

    def test_invalid_report_period(self, client):
        response = client.post(
            "/api/v1/teacher/reports",
            json=REPORT | {"period_start": "2026-10-02"},
            headers=auth(TEACHER_TOKEN),
        )
        assert response.status_code == 422

    def test_dependency_failure_is_a_200_with_fallback(self, make_client, adapter_kwargs):
        generator = MockContentGenerationAdapter(
            faults=FaultInjector("unavailable"), **adapter_kwargs
        )
        client = make_client(generation=generator)
        response = client.post(
            "/api/v1/tutor/experiences", json=EXPERIENCE, headers=auth(STUDENT_TOKEN)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["ui"]["blocks"] == [
            {"type": "fallback", "reason_code": "generation_unavailable", "text": None}
        ]

    def test_graph_timeout_is_504(self, make_client, settings, adapter_kwargs):
        slow = MockContentGenerationAdapter(faults=FaultInjector("timeout"), **adapter_kwargs)
        client = make_client(
            settings_override=settings.model_copy(update={"graph_timeout_s": 0.05}), generation=slow
        )
        response = client.post(
            "/api/v1/tutor/experiences", json=EXPERIENCE, headers=auth(STUDENT_TOKEN)
        )
        assert_error(response, 504, "workflow_timeout")
