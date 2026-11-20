"""Explicitly hypothetical data generator for the demonstration LinUCB checkpoint.

Nothing in this module estimates an intervention effect from EdNet or real students.
"""

from __future__ import annotations

import numpy as np


def generate_contexts(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    prior = rng.poisson(8, n)
    cold = prior == 0
    recent = rng.beta(2.2, 2.0, n)
    recent = np.minimum(recent, 0.8)  # the current decision follows an incorrect answer
    skill_attempts = np.asarray([rng.integers(0, value + 1) for value in prior])
    skill_cold = skill_attempts == 0
    skill_accuracy = rng.beta(2.0, 2.3, n)
    skill_accuracy[skill_cold] = 0.0
    consecutive = np.clip(rng.geometric(0.55, n), 1, 6)

    trend_missing = prior < 5
    trend = np.clip(rng.normal(0, 0.25, n), -1, 1)
    trend[trend_missing] = 0.0
    response_missing = rng.random(n) < 0.04
    response = np.clip(rng.lognormal(2.8, 0.55, n), 2, 180)
    response[response_missing] = 0.0
    since_missing = cold | (rng.random(n) < 0.02)
    since = np.clip(rng.lognormal(7.0, 1.0, n), 5, 604800)
    since[since_missing] = 0.0
    difficulty_missing = rng.random(n) < 0.02
    difficulty = rng.choice([0.0, 0.5, 1.0], n, p=[0.35, 0.45, 0.20])
    difficulty[difficulty_missing] = 0.0
    remediation_count = rng.poisson(np.minimum(prior / 5, 3))
    skill_remediation = np.asarray([rng.integers(0, value + 1) for value in remediation_count])
    recovery_missing = remediation_count == 0
    recovery = rng.beta(2.0, 2.0, n)
    recovery[recovery_missing] = 0.0
    return np.column_stack(
        [
            prior,
            recent,
            skill_attempts,
            skill_accuracy,
            consecutive,
            trend,
            response,
            since,
            difficulty,
            remediation_count,
            skill_remediation,
            recovery,
            cold.astype(float),
            skill_cold.astype(float),
            trend_missing.astype(float),
            response_missing.astype(float),
            since_missing.astype(float),
            difficulty_missing.astype(float),
            recovery_missing.astype(float),
        ]
    ).astype(float)


def recovery_probabilities(x: np.ndarray) -> np.ndarray:
    recent = x[:, 1]
    skill_accuracy = np.where(x[:, 13] > 0.5, recent, x[:, 3])
    consecutive = x[:, 4]
    difficulty = x[:, 8]
    cold = x[:, 12]
    prior_skill_remediation = x[:, 10]
    severity = np.clip(1.0 - skill_accuracy + 0.10 * consecutive + 0.15 * difficulty, 0, 1.8)
    base = 0.18 + 0.30 * recent + 0.24 * skill_accuracy - 0.035 * consecutive
    effects = np.column_stack(
        [
            0.07 + 0.14 * (consecutive <= 1) * (1 - difficulty),
            0.11 + 0.12 * cold,
            0.06 + 0.20 * severity,
            0.09 + 0.14 * ((skill_accuracy >= 0.35) & (skill_accuracy <= 0.75)),
            0.05 + 0.20 * (consecutive >= 3) + 0.05 * np.minimum(prior_skill_remediation, 2),
        ]
    )
    return np.clip(base[:, None] + effects, 0.03, 0.97)


def rule_actions(x: np.ndarray) -> np.ndarray:
    actions = np.ones(len(x), dtype=int)
    for i, row in enumerate(x):
        if row[12] > 0.5 or row[13] > 0.5:
            actions[i] = 1
        elif row[4] >= 3 or row[10] >= 2:
            actions[i] = 4
        elif row[2] >= 2 and row[3] < 0.5:
            actions[i] = 2
        elif row[2] >= 2 and row[3] <= 0.8:
            actions[i] = 3
        elif row[15] < 0.5 and row[6] < 15 and row[4] < 2:
            actions[i] = 0
    return actions
