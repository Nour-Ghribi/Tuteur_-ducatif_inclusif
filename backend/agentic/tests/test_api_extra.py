"""Progress and asset endpoints, and the development harness."""

import re

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tutor_agentic.assets import AssetRegistry
from tutor_agentic.config import Settings
from tutor_agentic.dev_server import create_dev_app

from .conftest import STUDENT_TOKEN, TEACHER_TOKEN, auth


class TestProgress:
    def test_empty_state(self, make_client):
        response = make_client().get("/api/v1/tutor/progress", headers=auth(STUDENT_TOKEN))
        assert response.status_code == 200
        assert response.json()["ui"]["blocks"][0]["message_code"] == "no_progress_yet"

    def test_teachers_have_no_learner_progress(self, make_client):
        assert (
            make_client().get("/api/v1/tutor/progress", headers=auth(TEACHER_TOKEN)).status_code
            == 403
        )

    def test_requires_authentication(self, make_client):
        assert make_client().get("/api/v1/tutor/progress").status_code == 401


class TestAssets:
    @pytest.fixture
    def registry_and_id(self, tmp_path):
        registry = AssetRegistry()
        path = tmp_path / "fig.png"
        Image.new("RGB", (4, 4), (10, 20, 30)).save(path)
        return registry, registry.register(path).asset_id

    def test_registered_image_is_served_to_authenticated_users(self, make_client, registry_and_id):
        registry, asset_id = registry_and_id
        client = make_client(assets=registry)
        response = client.get(f"/api/v1/assets/{asset_id}", headers=auth(STUDENT_TOKEN))
        assert response.status_code == 200 and response.headers["content-type"] == "image/png"
        assert response.content[:4] == b"\x89PNG"

    def test_requires_authentication(self, make_client, registry_and_id):
        registry, asset_id = registry_and_id
        assert make_client(assets=registry).get(f"/api/v1/assets/{asset_id}").status_code == 401

    @pytest.mark.parametrize("asset_id", ["img-unknown", "..%2F..%2Fetc%2Fpasswd", "a" * 80])
    def test_unknown_or_malformed_ids_are_not_served(self, make_client, registry_and_id, asset_id):
        registry, _ = registry_and_id
        response = make_client(assets=registry).get(
            f"/api/v1/assets/{asset_id}", headers=auth(STUDENT_TOKEN)
        )
        assert response.status_code in (404, 422)

    def test_a_deleted_file_is_not_served(self, make_client, registry_and_id):
        registry, asset_id = registry_and_id
        registry.get(asset_id).path.unlink()
        response = make_client(assets=registry).get(
            f"/api/v1/assets/{asset_id}", headers=auth(STUDENT_TOKEN)
        )
        assert response.status_code == 404


class TestDevHarness:
    def test_refuses_to_run_outside_development(self):
        with pytest.raises(RuntimeError):
            create_dev_app(Settings(_env_file=None, environment="staging", allow_mocks=True))

    def test_generates_throwaway_tokens_and_serves_the_workflows(self, capsys):
        app = create_dev_app(Settings(_env_file=None, environment="test"))
        with TestClient(app) as client:
            tokens = dict(re.findall(r"\[dev\] (\w+) token: (\S+)", capsys.readouterr().out))
            assert set(tokens) == {"student", "teacher"}
            assert client.get("/ready").json()["using_mocks"] is True
            assert (
                client.post(
                    "/api/v1/tutor/experiences", json={"message": "x", "course_id": "c"}
                ).status_code
                == 401
            )
            ok = client.post(
                "/api/v1/tutor/experiences",
                json={"message": "Quiz me", "course_id": "demo-bio-101", "topic": "photosynthèse"},
                headers=auth(tokens["student"]),
            )
            assert ok.status_code == 200 and ok.json()["ui"]["meta"]["simulated"] is True

    def test_cors_is_limited_to_the_dev_frontend(self):
        client = TestClient(create_dev_app(Settings(_env_file=None, environment="test")))
        allowed = client.options(
            "/api/v1/tutor/progress",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        denied = client.options(
            "/api/v1/tutor/progress",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )
        assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
        assert "access-control-allow-origin" not in denied.headers
