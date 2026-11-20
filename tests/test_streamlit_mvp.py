from pathlib import Path

from streamlit.testing.v1 import AppTest

from tuteur.adaptive.database import SQLiteRepository
from tuteur.config import get_settings

ROOT = Path(__file__).resolve().parents[1]


def button(app: AppTest, label: str):
    return next(element for element in app.button if element.label == label)


def radio(app: AppTest, label: str):
    return next(element for element in app.radio if element.label == label)


def test_streamlit_mock_journey_uses_linucb_and_observes_recovery(tmp_path, monkeypatch):
    database = tmp_path / "streamlit.sqlite3"
    monkeypatch.setenv("ADAPTIVE_MODE", "mock")
    monkeypatch.setenv("ADAPTIVE_DB_PATH", str(database))
    monkeypatch.setenv(
        "ADAPTIVE_POLICY_CHECKPOINT",
        str(ROOT / "models" / "linucb_demo_v1.json"),
    )
    get_settings.cache_clear()

    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    assert not app.exception
    button(app, "1. Démarrer une session et générer une question").click().run(timeout=30)
    radio(app, "Votre réponse").set_value("Les racines")
    button(app, "2. Valider la réponse initiale").click().run(timeout=30)

    assert not app.exception
    assert not app.error
    assert any("Décision produite par le checkpoint LinUCB" in item.value for item in app.success)
    button(app, "3. Valider la récupération").click().run(timeout=30)
    assert not app.exception
    assert not app.error
    assert any("Récupération observée" in item.value for item in app.success)

    repository = SQLiteRepository(database)
    saved = repository.fetchone(
        """SELECT r.policy_type,r.provenance,o.status,o.recovered
        FROM remediation_recommendations r JOIN recovery_outcomes o
        ON o.recommendation_id=r.id ORDER BY r.seq DESC LIMIT 1"""
    )
    assert saved is not None
    assert dict(saved) == {
        "policy_type": "LinUCB",
        "provenance": "simulation_trained",
        "status": "observed",
        "recovered": 1,
    }
