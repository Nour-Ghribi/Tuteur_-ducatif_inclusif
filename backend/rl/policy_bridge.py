"""Bridges the agentic contract (LearnerFeatures + ActivityOption list) to the
LinUCB AdaptiveTutorService which works with StudentState + SQL history.

The RL service receives per-request feature snapshots (no DB access from
here); it maps them directly to the LinUCB context vector so the policy can
score available arms without needing the student's full history in this
process.  The SQLite history remains in the agentic/MLOps service; this
service is stateless for recommendations.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from .schemas import (
    ActivityOption,
    Difficulty,
    LearnerFeatures,
    RecommendationResponse,
)

# Map agentic difficulty strings to tuteur difficulty floats
_DIFF_VALUE: dict[str, float] = {"easy": 0.0, "medium": 0.5, "hard": 1.0}
_DIFF_FROM_FLOAT: list[tuple[float, str]] = [
    (0.33, "easy"),
    (0.66, "medium"),
    (1.01, "hard"),
]


def _difficulty_from_score(score: float | None) -> str:
    if score is None:
        return "medium"
    for threshold, label in _DIFF_FROM_FLOAT:
        if score < threshold:
            return label
    return "hard"


def _choose_rule_based(
    features: LearnerFeatures,
    available: list[ActivityOption],
    student_ref: str,
    topic: str,
) -> RecommendationResponse:
    """Fallback rule-based policy used when no LinUCB checkpoint is loaded.

    Rules (mirrors RuleBasedPolicy from adaptive/policy.py but operates on
    the agentic LearnerFeatures instead of the full StudentState):
      - Cold start (no scores)         → explanation, easy
      - Last outcome incorrect         → remediation activity (exercise easy)
      - Recent mean score < 0.5        → exercise, easy
      - Recent mean score 0.5–0.75     → quiz, medium
      - Recent mean score > 0.75       → quiz or exercise, hard
    """
    scores = features.recent_scores
    mean = sum(scores) / len(scores) if scores else None
    last = features.last_outcome

    if not scores:
        target_type, target_diff = "explanation", "easy"
    elif last == "incorrect" or (mean is not None and mean < 0.5):
        target_type, target_diff = "exercise", "easy"
    elif mean is not None and mean < 0.75:
        target_type, target_diff = "quiz", "medium"
    else:
        target_type, target_diff = "quiz", "hard"

    # Pick the best matching option from the available catalog.
    # Exact match first, then relax difficulty, then relax type.
    candidate = (
        _exact(available, target_type, target_diff)
        or _relax_diff(available, target_type)
        or _relax_type(available, target_diff)
        or available[0]
    )

    return RecommendationResponse(
        recommendation_id=f"rec-{uuid.uuid4().hex[:12]}",
        activity_type=candidate.activity_type,
        difficulty=candidate.difficulty,
        topic=candidate.topic,
        policy_version="rule-based-v1",
        rationale=f"Rule: scores={[round(s,2) for s in scores[-3:]]}, last={last}",
        simulated=False,
    )


def _exact(opts: list[ActivityOption], typ: str, diff: str) -> ActivityOption | None:
    return next((o for o in opts if o.activity_type == typ and o.difficulty == diff), None)


def _relax_diff(opts: list[ActivityOption], typ: str) -> ActivityOption | None:
    return next((o for o in opts if o.activity_type == typ), None)


def _relax_type(opts: list[ActivityOption], diff: str) -> ActivityOption | None:
    return next((o for o in opts if o.difficulty == diff), None)


def recommend(
    features: LearnerFeatures,
    available: list[ActivityOption],
    student_ref: str,
    topic: str,
    linucb_policy=None,
) -> RecommendationResponse:
    """Entry point called by the FastAPI handler.

    If a LinUCB policy checkpoint is provided and loaded, it is used.
    Otherwise falls back to rule-based.
    """
    if linucb_policy is not None:
        try:
            return _linucb_recommend(linucb_policy, features, available, student_ref, topic)
        except Exception:
            pass  # checkpoint failed: fall through to rule-based

    return _choose_rule_based(features, available, student_ref, topic)


def _linucb_recommend(
    policy,
    features: LearnerFeatures,
    available: list[ActivityOption],
    student_ref: str,
    topic: str,
) -> RecommendationResponse:
    """Call the LinUCB policy with a synthetic StudentState built from the
    agentic LearnerFeatures.  Only the fields that map cleanly are populated;
    missing fields use cold-start safe defaults.
    """
    import numpy as np
    from tuteur.adaptive.models import StudentState

    scores = features.recent_scores or []
    n = len(scores)
    recent_5 = scores[-5:] if scores else []
    mean_recent = float(np.mean(recent_5)) if recent_5 else 0.5

    # Build a minimal valid StudentState for the vector encoder.
    state = StudentState(
        student_id=student_ref,
        skill_id=hashlib.sha256(topic.encode()).hexdigest()[:12],
        current_attempt_id=f"req-{uuid.uuid4().hex[:8]}",
        decision_time=datetime.now(UTC),
        prior_answer_count=n,
        recent_accuracy_5_including_current=mean_recent,
        skill_attempt_count_prior=n,
        skill_accuracy_prior=mean_recent if n > 0 else None,
        consecutive_failures_including_current=max(
            1,
            sum(1 for s in reversed(scores) if s < 0.5)
            if scores and features.last_outcome == "incorrect"
            else 1,
        ),
        prior_displayed_remediation_count=0,
        prior_displayed_skill_remediation_count=0,
        student_cold_start=(n == 0),
        skill_cold_start=(n == 0),
    )

    decision = policy.recommend(state)

    # Map the LinUCB strategy id to an activity type + difficulty.
    strategy_map = {
        "A0_guided_hint": ("exercise", "easy"),
        "A1_simplified_explanation": ("explanation", "easy"),
        "A2_worked_example": ("explanation", "medium"),
        "A3_scaffolded_mcq": ("quiz", "medium"),
        "A4_targeted_revision": ("revision", "hard"),
    }
    act_type, diff = strategy_map.get(decision.strategy_id, ("quiz", "medium"))

    candidate = (
        _exact(available, act_type, diff)
        or _relax_diff(available, act_type)
        or _relax_type(available, diff)
        or available[0]
    )

    return RecommendationResponse(
        recommendation_id=f"rec-{uuid.uuid4().hex[:12]}",
        activity_type=candidate.activity_type,
        difficulty=candidate.difficulty,
        topic=candidate.topic,
        policy_version=decision.policy_version,
        rationale=decision.reason,
        simulated=False,
    )
