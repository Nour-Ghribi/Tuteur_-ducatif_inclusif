from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from tuteur.adaptive.database import SQLiteRepository
from tuteur.adaptive.models import ACTION_IDS, FEATURE_NAMES_19D, StudentState
from tuteur.adaptive.policy import LinUCBPolicy, RuleBasedPolicy
from tuteur.adaptive.service import AdaptiveTutorService
from tuteur.adaptive.state import StudentStateBuilder
from tuteur.demo_llm import DeterministicDemoLLM, OfflineDemoStore
from tuteur.generation import Tutor
from tuteur.schemas import QuizItem

ROOT = Path(__file__).resolve().parents[1]


def item(question: str = "Quel pigment capte la lumière ?") -> QuizItem:
    return QuizItem(
        type="qcm",
        question=question,
        choices=["Chlorophylle", "Eau", "Racines", "Oxygène"],
        answer="Chlorophylle",
        explanation="Le pigment vert capte la lumière.",
        difficulty="moyen",
        competence="photosynthèse",
        source_pages=[1],
    )


def state(**overrides) -> StudentState:
    values = {
        "student_id": "student",
        "skill_id": "skill",
        "current_attempt_id": "attempt",
        "decision_time": datetime(2026, 1, 1, tzinfo=UTC),
        "prior_answer_count": 0,
        "recent_accuracy_5_including_current": 0.0,
        "skill_attempt_count_prior": 0,
        "skill_accuracy_prior": None,
        "consecutive_failures_including_current": 1,
        "recent_performance_trend_3v3": None,
        "current_response_time_s": 20.0,
        "time_since_previous_answer_s": None,
        "authored_question_difficulty": 0.5,
        "prior_displayed_remediation_count": 0,
        "prior_displayed_skill_remediation_count": 0,
        "prior_observed_recovery_rate": None,
        "student_cold_start": True,
        "skill_cold_start": True,
    }
    values.update(overrides)
    return StudentState(**values)


def test_state_vector_contract_and_checkpoint_restore_parity():
    current = state()
    assert current.to_vector().shape == (len(FEATURE_NAMES_19D),)
    assert np.isfinite(current.to_vector()).all()
    assert current.to_vector()[-5:].tolist() == [1.0, 0.0, 1.0, 0.0, 1.0]

    checkpoint = ROOT / "models" / "linucb_demo_v1.json"
    first = LinUCBPolicy.load(checkpoint)
    second = LinUCBPolicy.load(checkpoint)
    assert first.recommend(current).strategy_id == second.recommend(current).strategy_id
    assert first.metadata["provenance"] == "simulation_trained"


def test_rule_baseline_has_all_five_reachable_actions():
    policy = RuleBasedPolicy()
    cases = [
        state(
            prior_answer_count=2,
            skill_attempt_count_prior=1,
            skill_accuracy_prior=1.0,
            student_cold_start=False,
            skill_cold_start=False,
            current_response_time_s=5.0,
        ),
        state(
            prior_answer_count=2,
            skill_attempt_count_prior=2,
            skill_accuracy_prior=1.0,
            student_cold_start=False,
            skill_cold_start=False,
            current_response_time_s=30.0,
        ),
        state(
            prior_answer_count=2,
            skill_attempt_count_prior=2,
            skill_accuracy_prior=0.0,
            student_cold_start=False,
            skill_cold_start=False,
            consecutive_failures_including_current=2,
        ),
        state(
            prior_answer_count=5,
            skill_attempt_count_prior=2,
            skill_accuracy_prior=0.5,
            student_cold_start=False,
            skill_cold_start=False,
            recent_accuracy_5_including_current=0.2,
        ),
        state(
            prior_answer_count=5,
            skill_attempt_count_prior=2,
            skill_accuracy_prior=0.5,
            student_cold_start=False,
            skill_cold_start=False,
            prior_displayed_skill_remediation_count=2,
        ),
    ]
    assert {policy.recommend(case).strategy_id for case in cases} == set(ACTION_IDS)


def test_state_builder_is_cold_start_and_excludes_future_event(tmp_path):
    repo = SQLiteRepository(tmp_path / "state.sqlite3")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    session = repo.create_session("student", "course", "Cours", "fixture", at=start)
    question_id, _ = repo.save_question(
        session,
        "course",
        item(),
        prompt_tag="test",
        model_version="mock",
        at=start,
    )
    attempt = repo.present_question(question_id, session, "student", start, "current")
    repo.submit_answer(attempt, "Eau", start + timedelta(seconds=10))

    future_question, _ = repo.save_question(
        session,
        "course",
        item("Question future différente ?"),
        prompt_tag="test",
        model_version="mock",
        at=start + timedelta(minutes=1),
    )
    future = repo.present_question(
        future_question, session, "student", start + timedelta(minutes=1), "future"
    )
    repo.submit_answer(future, "Chlorophylle", start + timedelta(minutes=2))

    built = StudentStateBuilder(repo).build("current")
    assert built.prior_answer_count == 0
    assert built.student_cold_start is True
    assert built.recent_accuracy_5_including_current == 0.0
    assert built.current_response_time_s == 10.0


def test_missing_primary_policy_is_explicit_rule_fallback(tmp_path):
    repo = SQLiteRepository(tmp_path / "fallback.sqlite3")
    tutor = Tutor(
        store=OfflineDemoStore.from_path(ROOT / "data" / "raw" / "photosynthese.md"),
        llm=DeterministicDemoLLM(),
    )
    service = AdaptiveTutorService(
        repo,
        tutor,
        primary_policy=None,
        primary_policy_error="checkpoint missing in test",
    )
    decision, used_fallback, error = service._decide(state())
    assert used_fallback is True
    assert error == "checkpoint missing in test"
    assert decision.provenance == "rule_based_fallback"
    assert decision.policy_type.startswith("Rule-Based Baseline")
    assert "checkpoint missing in test" in decision.reason


@pytest.mark.parametrize("strategy_id", ACTION_IDS)
def test_all_strategy_prompts_use_structured_offline_path(strategy_id):
    tutor = Tutor(
        store=OfflineDemoStore.from_path(ROOT / "data" / "raw" / "photosynthese.md"),
        llm=DeterministicDemoLLM(),
    )
    output = tutor.adaptive_remediate(
        strategy_id=strategy_id,
        question="Quel élément aide la plante à capter la lumière ?",
        student_answer="Les racines",
        correct_answer="La chlorophylle",
        competence="photosynthèse",
    )
    assert output.strategy_id == strategy_id
    assert output.retry_question.question != "Quel élément aide la plante à capter la lumière ?"
    assert output.retry_question.competence == "photosynthèse"


def test_complete_offline_flow_uses_loaded_linucb_and_persists_recovery(tmp_path):
    repo = SQLiteRepository(tmp_path / "mvp.sqlite3")
    tutor = Tutor(
        store=OfflineDemoStore.from_path(ROOT / "data" / "raw" / "photosynthese.md"),
        llm=DeterministicDemoLLM(),
    )
    policy = LinUCBPolicy.load(ROOT / "models" / "linucb_demo_v1.json")
    counts_before = policy.model.counts.copy()
    service = AdaptiveTutorService(repo, tutor, policy)
    session = service.start_session(
        student_id="demo-student",
        course_id="course",
        title="Photosynthèse",
        source="offline fixture",
        session_id="session",
    )
    question_id, question = service.generate_quiz_question(
        session_id=session,
        course_id="course",
        topic="photosynthèse",
    )
    attempt = repo.present_question(question_id, session, "demo-student")
    assert repo.submit_answer(attempt, "Les racines") is False
    flow = service.handle_failure(
        session_id=session,
        course_id="course",
        failed_attempt_id=attempt,
        failed_question_id=question_id,
        question=question,
        student_answer="Les racines",
    )
    assert flow.used_fallback is False
    assert flow.decision.policy_type == "LinUCB"
    assert flow.decision.provenance == "simulation_trained"
    service.mark_remediation_event(flow, "displayed")
    service.mark_remediation_event(flow, "viewed")
    service.mark_remediation_event(flow, "completed")
    followup = repo.present_question(flow.followup_question_id, session, "demo-student")
    assert repo.submit_answer(followup, flow.remediation.retry_question.answer) is True
    assert service.observe_followup(flow.recommendation_id, followup) is True

    saved = repo.fetchone(
        """SELECT r.state_json,r.vector_json,r.policy_version,r.provenance,
        r.assignment_mechanism,o.status,o.recovered
        FROM remediation_recommendations r JOIN recovery_outcomes o
        ON o.recommendation_id=r.id WHERE r.id=?""",
        (flow.recommendation_id,),
    )
    assert saved is not None
    assert saved["provenance"] == "simulation_trained"
    assert saved["assignment_mechanism"] == "linucb_ucb"
    assert saved["status"] == "observed"
    assert saved["recovered"] == 1
    assert np.array_equal(policy.model.counts, counts_before), "V1 must not learn online"


def test_mock_retry_differs_after_multiple_quiz_generations():
    tutor = Tutor(
        store=OfflineDemoStore.from_path(ROOT / "data" / "raw" / "photosynthese.md"),
        llm=DeterministicDemoLLM(),
    )
    first = tutor.quiz(topic="photosynthèse", n=1).items[0]
    second = tutor.quiz(topic="photosynthèse", n=1).items[0]
    assert first.question != second.question

    for failed in (first, second):
        output = tutor.adaptive_remediate(
            strategy_id="A1_simplified_explanation",
            question=failed.question,
            student_answer="réponse incorrecte",
            correct_answer=failed.answer,
            competence=failed.competence,
        )
        assert output.retry_question.question != failed.question
