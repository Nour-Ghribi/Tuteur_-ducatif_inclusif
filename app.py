"""Streamlit entry point for the GenAI/RAG + LinUCB adaptive tutor MVP."""

from __future__ import annotations

import uuid
from pathlib import Path

import streamlit as st

from tuteur.adaptive.database import SQLiteRepository
from tuteur.adaptive.policy import LinUCBPolicy
from tuteur.adaptive.service import AdaptiveTutorService, FailureFlow
from tuteur.config import get_settings
from tuteur.demo_llm import DeterministicDemoLLM, OfflineDemoStore
from tuteur.generation import Tutor
from tuteur.llm import LLM
from tuteur.schemas import QuizItem
from tuteur.vectorstore import VectorStore

ROOT = Path(__file__).resolve().parent
SETTINGS = get_settings()
STRATEGY_LABELS = {
    "A0_guided_hint": "A0 — Indice guidé",
    "A1_simplified_explanation": "A1 — Explication simplifiée",
    "A2_worked_example": "A2 — Exemple résolu",
    "A3_scaffolded_mcq": "A3 — QCM étayé",
    "A4_targeted_revision": "A4 — Révision ciblée",
}


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def make_service(mode: str) -> tuple[AdaptiveTutorService, str | None]:
    settings = get_settings()
    repository = SQLiteRepository(resolve(settings.adaptive_db_path))
    checkpoint_error = None
    try:
        primary = LinUCBPolicy.load(resolve(settings.adaptive_policy_checkpoint))
    except Exception as exc:  # noqa: BLE001 - checkpoint boundary must activate visible fallback
        primary = None
        checkpoint_error = f"{type(exc).__name__}: {exc}"

    if mode == "MOCK DEMO":
        store = OfflineDemoStore.from_path(ROOT / "data" / "raw" / "photosynthese.md")
        tutor = Tutor(store=store, llm=DeterministicDemoLLM())
    else:
        # This preserves the repository's actual configurable RAG and OpenAI-compatible LLM path.
        tutor = Tutor(store=VectorStore(settings), llm=LLM(settings))
    service = AdaptiveTutorService(
        repository,
        tutor,
        primary,
        primary_policy_error=checkpoint_error,
    )
    return service, checkpoint_error


def render_remediation(flow: FailureFlow) -> None:
    st.subheader("Remédiation adaptative")
    if flow.used_fallback:
        st.error(f"RÈGLE DE REPLI — cette décision n'est pas LinUCB. {flow.fallback_error}")
    else:
        st.success("Décision produite par le checkpoint LinUCB chargé.")
    left, right = st.columns(2)
    left.metric("Stratégie", STRATEGY_LABELS[flow.decision.strategy_id])
    right.metric("Version", flow.decision.policy_version)
    st.caption(
        f"Politique: {flow.decision.policy_type} · provenance: "
        f"{flow.decision.provenance} · affectation: {flow.decision.assignment_mechanism}"
    )
    st.info(flow.decision.reason)
    payload = flow.remediation.model_dump(mode="json", exclude={"retry_question"})
    for key, value in payload.items():
        if key not in {"strategy_id", "source_pages"}:
            st.write(f"**{key.replace('_', ' ').capitalize()} :**", value)
    st.caption(f"Pages RAG citées: {flow.remediation.source_pages}")


def choices(item: QuizItem) -> list[str]:
    return item.choices if item.type == "qcm" else ["Vrai", "Faux"]


st.set_page_config(page_title="Tuteur adaptatif LinUCB", page_icon="🎓", layout="wide")
st.title("Tuteur adaptatif — GenAI/RAG + LinUCB")
st.caption(
    "MVP V1 : checkpoint entraîné sur simulation hypothétique. "
    "Aucune efficacité éducative réelle n'est revendiquée."
)

with st.sidebar:
    default_mode_index = 1 if SETTINGS.adaptive_mode.casefold() == "real" else 0
    mode = st.radio(
        "Mode d'exécution",
        ["MOCK DEMO", "REAL LLM"],
        index=default_mode_index,
        horizontal=False,
    )
    st.warning(
        "MOCK DEMO est entièrement hors ligne et déterministe."
        if mode == "MOCK DEMO"
        else "REAL LLM utilise réellement le fournisseur et le RAG configurés dans .env."
    )
    student_id = st.text_input("Identifiant pseudonyme", value="demo-student-001")
    reading_level = st.selectbox("Niveau de lecture", ["standard", "simplifie"])
    if st.button("Réinitialiser l'écran"):
        for key in list(st.session_state):
            del st.session_state[key]
        st.rerun()

runtime_key = f"runtime:{mode}"
if runtime_key not in st.session_state:
    try:
        st.session_state[runtime_key] = make_service(mode)
    except Exception as exc:  # noqa: BLE001 - UI boundary reports provider/setup failures
        st.error(
            "Initialisation impossible. En mode REAL LLM, vérifiez le fournisseur, les "
            f"embeddings et l'index RAG. Détail: {type(exc).__name__}: {exc}"
        )
        st.stop()
service, checkpoint_error = st.session_state[runtime_key]

if checkpoint_error:
    st.error(
        "Checkpoint LinUCB indisponible/invalide. Les décisions utiliseront explicitement "
        f"la baseline règle-based. Détail: {checkpoint_error}"
    )
else:
    st.success("Checkpoint LinUCB 19D validé et chargé comme politique principale.")

course_id = "course-photosynthesis-v1" if mode == "MOCK DEMO" else "course-rag-v1"
topic = st.text_input("Thème du quiz", value="photosynthèse")

if st.button("1. Démarrer une session et générer une question", type="primary"):
    try:
        session_id = f"session-{uuid.uuid4().hex}"
        service.start_session(
            student_id=student_id,
            course_id=course_id,
            title=topic,
            source="offline fixture" if mode == "MOCK DEMO" else "configured RAG index",
            reading_level=reading_level,
            session_id=session_id,
        )
        question_id, item = service.generate_quiz_question(
            session_id=session_id,
            course_id=course_id,
            topic=topic,
            reading_level=reading_level,
        )
        attempt_id = service.repository.present_question(question_id, session_id, student_id)
        st.session_state.current = {
            "session_id": session_id,
            "question_id": question_id,
            "attempt_id": attempt_id,
            "item": item,
            "course_id": course_id,
            "reading_level": reading_level,
        }
        st.session_state.pop("flow", None)
        st.session_state.pop("result", None)
        st.session_state.pop("followup_attempt_id", None)
        st.session_state.pop("recovered", None)
        st.session_state.pop("remediation_viewed", None)
        st.rerun()
    except Exception as exc:  # noqa: BLE001 - UI boundary must show external failures
        st.error(
            "La génération du quiz a échoué; aucun mock silencieux n'a été substitué. "
            f"Détail: {type(exc).__name__}: {exc}"
        )

current = st.session_state.get("current")
if current:
    item: QuizItem = current["item"]
    st.subheader("Question initiale")
    st.write(item.question)
    initial_answer = st.radio("Votre réponse", choices(item), key="initial_answer")
    if st.button("2. Valider la réponse initiale", disabled="result" in st.session_state):
        try:
            correct = service.repository.submit_answer(current["attempt_id"], initial_answer)
            st.session_state.result = correct
            if correct is False:
                st.session_state.flow = service.handle_failure(
                    session_id=current["session_id"],
                    course_id=current["course_id"],
                    failed_attempt_id=current["attempt_id"],
                    failed_question_id=current["question_id"],
                    question=item,
                    student_answer=initial_answer,
                    reading_level=current["reading_level"],
                )
            st.rerun()
        except Exception as exc:  # noqa: BLE001 - UI boundary reports orchestration failure
            st.error(f"Soumission/orchestration impossible: {type(exc).__name__}: {exc}")

if st.session_state.get("result") is True:
    st.success("Bonne réponse — aucune remédiation n'est nécessaire.")
elif st.session_state.get("result") is False:
    flow: FailureFlow | None = st.session_state.get("flow")
    if flow is None:
        st.error("La remédiation n'a pas pu être générée; aucun résultat de récupération n'est créé.")
    else:
        service.mark_remediation_event(flow, "displayed")
        render_remediation(flow)
        if st.button("J'ai consulté la remédiation"):
            service.mark_remediation_event(flow, "viewed")
            st.session_state.remediation_viewed = True
        retry = flow.remediation.retry_question
        st.subheader("Question de récupération")
        st.write(retry.question)
        retry_answer = st.radio("Votre nouvelle réponse", choices(retry), key="retry_answer")
        if "followup_attempt_id" not in st.session_state:
            st.session_state.followup_attempt_id = service.repository.present_question(
                flow.followup_question_id,
                current["session_id"],
                student_id,
            )
        if st.button("3. Valider la récupération", disabled="recovered" in st.session_state):
            try:
                service.mark_remediation_event(flow, "completed")
                service.repository.submit_answer(
                    st.session_state.followup_attempt_id,
                    retry_answer,
                )
                st.session_state.recovered = service.observe_followup(
                    flow.recommendation_id,
                    st.session_state.followup_attempt_id,
                )
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - UI boundary reports persistence failure
                st.error(f"Évaluation de récupération impossible: {type(exc).__name__}: {exc}")
        if "recovered" in st.session_state:
            if st.session_state.recovered:
                st.success("Récupération observée sur la question de suivi.")
            else:
                st.warning("Récupération non observée sur ce suivi (ce n'est pas une donnée manquante).")

with st.expander("Audit de la session persistée"):
    rows = service.repository.fetchall(
        """SELECT r.strategy_id,r.policy_type,r.policy_version,r.provenance,
        r.assignment_mechanism,o.status,o.recovered
        FROM remediation_recommendations r
        LEFT JOIN recovery_outcomes o ON o.recommendation_id=r.id
        WHERE r.student_id=? ORDER BY r.seq DESC LIMIT 20""",
        (student_id,),
    )
    st.dataframe([dict(row) for row in rows], width="stretch")
