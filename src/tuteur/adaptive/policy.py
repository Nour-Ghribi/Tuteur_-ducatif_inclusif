from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import numpy as np

from tuteur.adaptive.models import (
    ACTION_IDS,
    FEATURE_NAMES_19D,
    VECTOR_SCHEMA_VERSION,
    RemediationDecision,
    StudentState,
)

ACTION_NAMES = (
    "Guided Hint",
    "Simplified Explanation",
    "Worked Example",
    "Scaffolded MCQ",
    "Targeted Revision",
)


class RemediationPolicy(Protocol):
    def recommend(self, state: StudentState) -> RemediationDecision: ...


class RuleBasedPolicy:
    version = "rule-based-v1"

    def recommend(self, state: StudentState) -> RemediationDecision:
        if state.student_cold_start or state.skill_cold_start:
            action, reason = 1, "Cold-start: explication simple avant personnalisation."
        elif (
            state.consecutive_failures_including_current >= 3
            or state.prior_displayed_skill_remediation_count >= 2
        ):
            action, reason = 4, "Échecs répétés ou remédiations précédentes: révision ciblée."
        elif state.skill_attempt_count_prior >= 2 and state.skill_accuracy_prior < 0.5:
            action, reason = 2, "Maîtrise antérieure faible: exemple résolu étape par étape."
        elif state.skill_attempt_count_prior >= 2 and state.skill_accuracy_prior <= 0.8:
            action, reason = 3, "Maîtrise intermédiaire: exercice QCM échafaudé."
        elif (
            state.current_response_time_s is not None
            and state.current_response_time_s < 15
            and state.consecutive_failures_including_current < 2
        ):
            action, reason = 0, "Réponse rapide isolée: indice progressif."
        else:
            action, reason = 1, "Fallback pédagogique général: explication simplifiée."
        return RemediationDecision(
            strategy_id=ACTION_IDS[action],
            strategy_name=ACTION_NAMES[action],
            policy_type="Rule-Based Baseline — Not Trained RL",
            policy_version=self.version,
            state_hash=state.snapshot_hash(),
            input_valid=True,
            provenance="rule_based_fallback",
            reason=reason,
            assignment_mechanism="deterministic_rule",
            action_probability=1.0,
        )


@dataclass(frozen=True)
class FeatureScaler:
    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, matrix: np.ndarray) -> FeatureScaler:
        mean = matrix.mean(axis=0)
        scale = matrix.std(axis=0)
        scale[scale < 1e-12] = 1.0
        return cls(mean.astype(float), scale.astype(float))

    def transform(self, vector: np.ndarray) -> np.ndarray:
        vector = np.asarray(vector, dtype=float)
        if vector.shape[-1] != 19 or not np.isfinite(vector).all():
            raise ValueError("LinUCB expects 19 finite features")
        return (vector - self.mean) / self.scale


class DisjointLinUCB:
    """Disjoint LinUCB over recovery probability with known action costs."""

    def __init__(self, ridge: float, exploration: float, action_costs: tuple[float, ...]):
        self.ridge = float(ridge)
        self.exploration = float(exploration)
        self.action_costs = np.asarray(action_costs, dtype=float)
        if self.ridge <= 0 or self.exploration < 0:
            raise ValueError("ridge must be positive and exploration must be non-negative")
        if self.action_costs.shape != (len(ACTION_IDS),) or not np.isfinite(
            self.action_costs
        ).all():
            raise ValueError("one finite action cost is required for each stable action")
        self.dimension = 20  # 19 scaled values + intercept
        self.a_inv = np.repeat(
            (np.eye(self.dimension) / self.ridge)[None, :, :], len(ACTION_IDS), axis=0
        )
        self.b = np.zeros((len(ACTION_IDS), self.dimension), dtype=float)
        self.counts = np.zeros(len(ACTION_IDS), dtype=int)

    @staticmethod
    def _with_intercept(vector: np.ndarray) -> np.ndarray:
        return np.concatenate([np.asarray(vector, dtype=float), [1.0]])

    def components(self, vector: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x = self._with_intercept(vector)
        theta = np.einsum("aij,aj->ai", self.a_inv, self.b)
        mean = theta @ x
        width = np.sqrt(np.maximum(np.einsum("i,aij,j->a", x, self.a_inv, x), 0.0))
        return mean, width

    def select(self, vector: np.ndarray, explore: bool = True) -> int:
        mean, width = self.components(vector)
        bonus = self.exploration * width if explore else 0.0
        return int(np.argmax(mean + bonus - self.action_costs))

    def update(self, vector: np.ndarray, action: int, recovery: float) -> None:
        x = self._with_intercept(vector)
        inv = self.a_inv[action]
        inv_x = inv @ x
        self.a_inv[action] = inv - np.outer(inv_x, inv_x) / (1.0 + x @ inv_x)
        self.b[action] += float(recovery) * x
        self.counts[action] += 1


class LinUCBPolicy:
    def __init__(
        self, model: DisjointLinUCB, scaler: FeatureScaler, metadata: dict[str, object],
        checkpoint_path: Path | None = None,
    ):
        self.model = model
        self.scaler = scaler
        self.metadata = metadata
        self.checkpoint_path = checkpoint_path
        if metadata.get("vector_schema_version") != VECTOR_SCHEMA_VERSION:
            raise ValueError("checkpoint vector schema is incompatible")
        if tuple(metadata.get("feature_names", ())) != FEATURE_NAMES_19D:
            raise ValueError("checkpoint feature order is incompatible")
        if tuple(metadata.get("action_ids", ())) != ACTION_IDS:
            raise ValueError("checkpoint action order is incompatible")

    def recommend(self, state: StudentState) -> RemediationDecision:
        vector = self.scaler.transform(state.to_vector())
        action = self.model.select(vector, explore=True)
        mean, width = self.model.components(vector)
        return RemediationDecision(
            strategy_id=ACTION_IDS[action],
            strategy_name=ACTION_NAMES[action],
            policy_type="LinUCB",
            policy_version=str(self.metadata["policy_version"]),
            state_hash=state.snapshot_hash(),
            input_valid=True,
            provenance="simulation_trained",
            reason=(
                f"Highest LinUCB score for action {ACTION_IDS[action]} "
                f"(estimated recovery={mean[action]:.3f}, width={width[action]:.3f}); "
                "effects used for training were hypothetical."
            ),
            assignment_mechanism="linucb_ucb",
            action_probability=None,
        )

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "tuteur-linucb-checkpoint-v1",
            "metadata": self.metadata,
            "model": {
                "ridge": self.model.ridge,
                "exploration": self.model.exploration,
                "action_costs": self.model.action_costs.tolist(),
                "a_inv": self.model.a_inv.tolist(),
                "b": self.model.b.tolist(),
                "counts": self.model.counts.tolist(),
            },
            "scaler": {"mean": self.scaler.mean.tolist(), "scale": self.scaler.scale.tolist()},
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        envelope = {"sha256": hashlib.sha256(canonical.encode()).hexdigest(), **payload}
        path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> LinUCBPolicy:
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        digest = payload.pop("sha256")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(canonical.encode()).hexdigest() != digest:
            raise ValueError("LinUCB checkpoint hash mismatch")
        if payload.get("format") != "tuteur-linucb-checkpoint-v1":
            raise ValueError("unsupported LinUCB checkpoint format")
        spec = payload["model"]
        model = DisjointLinUCB(spec["ridge"], spec["exploration"], tuple(spec["action_costs"]))
        model.a_inv = np.asarray(spec["a_inv"], dtype=float)
        model.b = np.asarray(spec["b"], dtype=float)
        model.counts = np.asarray(spec["counts"], dtype=int)
        scaler = FeatureScaler(
            np.asarray(payload["scaler"]["mean"], dtype=float),
            np.asarray(payload["scaler"]["scale"], dtype=float),
        )
        if model.a_inv.shape != (len(ACTION_IDS), 20, 20):
            raise ValueError("checkpoint contains invalid LinUCB matrices")
        if model.b.shape != (len(ACTION_IDS), 20) or model.counts.shape != (len(ACTION_IDS),):
            raise ValueError("checkpoint contains invalid LinUCB parameters")
        if scaler.mean.shape != (19,) or scaler.scale.shape != (19,):
            raise ValueError("checkpoint contains an invalid 19D feature scaler")
        arrays = (model.a_inv, model.b, scaler.mean, scaler.scale)
        if not all(np.isfinite(array).all() for array in arrays) or np.any(scaler.scale <= 0):
            raise ValueError("checkpoint parameters must be finite and scales must be positive")
        return cls(model, scaler, payload["metadata"], path)


def checkpoint_metadata(config: dict[str, object]) -> dict[str, object]:
    return {
        "policy_version": "linucb-19d-synthetic-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "vector_schema_version": VECTOR_SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES_19D),
        "action_ids": list(ACTION_IDS),
        "provenance": "simulation_trained",
        "synthetic_notice": (
            "Action effects and rewards are explicitly hypothetical; no EdNet or real-student "
            "intervention effect was used or established."
        ),
        "training_config": config,
    }
