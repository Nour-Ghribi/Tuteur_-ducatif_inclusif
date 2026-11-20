from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from tuteur.adaptive.models import ACTION_IDS, FEATURE_NAMES_19D
from tuteur.adaptive.policy import (
    DisjointLinUCB,
    FeatureScaler,
    LinUCBPolicy,
    checkpoint_metadata,
)
from tuteur.adaptive.synthetic import (
    generate_contexts,
    recovery_probabilities,
    rule_actions,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(actions: np.ndarray, reward: np.ndarray) -> dict[str, object]:
    rows = np.arange(len(actions))
    chosen = reward[rows, actions]
    optimal = reward.max(axis=1)
    return {
        "expected_reward": float(chosen.mean()),
        "mean_regret": float((optimal - chosen).mean()),
        "action_distribution": (np.bincount(actions, minlength=5) / len(actions)).tolist(),
    }


def train(project: Path, config_path: Path) -> dict[str, object]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not config.get("frozen_before_evaluation"):
        raise ValueError("protocol must be frozen before evaluation")
    train_x = generate_contexts(int(config["training_budget"]), int(config["training_seed"]))
    train_p = recovery_probabilities(train_x)
    scaler = FeatureScaler.fit(train_x)
    model = DisjointLinUCB(
        float(config["ridge"]), float(config["exploration"]), tuple(config["action_costs"])
    )
    rng = np.random.default_rng(int(config["training_seed"]) + 1)
    for raw, probabilities in zip(train_x, train_p, strict=True):
        scaled = scaler.transform(raw)
        action = model.select(scaled, explore=True)
        recovery = float(rng.random() < probabilities[action])
        model.update(scaled, action, recovery)

    metadata = checkpoint_metadata(
        {
            **config,
            "config_sha256": sha256(config_path),
            "feature_dimension": len(FEATURE_NAMES_19D),
            "internal_dimension_with_intercept": len(FEATURE_NAMES_19D) + 1,
        }
    )
    policy = LinUCBPolicy(model, scaler, metadata)
    checkpoint = policy.save(project / str(config["checkpoint"]))

    eval_x = generate_contexts(int(config["evaluation_contexts"]), int(config["evaluation_seed"]))
    probabilities = recovery_probabilities(eval_x)
    reward = probabilities * float(config["recovery_weight"]) - np.asarray(config["action_costs"])
    scaled_eval = np.asarray([scaler.transform(row) for row in eval_x])
    linucb_actions = np.asarray([model.select(row, explore=True) for row in scaled_eval])
    rng_eval = np.random.default_rng(int(config["evaluation_seed"]) + 1)
    random_actions = rng_eval.integers(0, len(ACTION_IDS), len(eval_x))
    constant_means = reward.mean(axis=0)
    best_constant = np.full(len(eval_x), int(np.argmax(constant_means)))
    oracle = reward.argmax(axis=1)
    rules = rule_actions(eval_x)

    restored = LinUCBPolicy.load(checkpoint)
    restored_actions = np.asarray(
        [restored.model.select(restored.scaler.transform(row), explore=True) for row in eval_x]
    )
    report = {
        "protocol_version": config["protocol_version"],
        "config_sha256": sha256(config_path),
        "checkpoint": str(checkpoint.relative_to(project)),
        "checkpoint_sha256": sha256(checkpoint),
        "synthetic": True,
        "notice": metadata["synthetic_notice"],
        "training_budget": len(train_x),
        "evaluation_contexts": len(eval_x),
        "train_action_counts": model.counts.tolist(),
        "checkpoint_restore_action_parity": bool(np.array_equal(linucb_actions, restored_actions)),
        "metrics": {
            "linucb": evaluate(linucb_actions, reward),
            "rule_based": evaluate(rules, reward),
            "random": evaluate(random_actions, reward),
            "best_constant": evaluate(best_constant, reward),
            "oracle_upper_bound": evaluate(oracle, reward),
        },
    }
    report_path = project / str(config["evaluation_report"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path, default=Path("configs/linucb_demo_v1.json"))
    args = parser.parse_args()
    project = args.project.resolve()
    config = args.config if args.config.is_absolute() else project / args.config
    print(json.dumps(train(project, config), indent=2))


if __name__ == "__main__":
    main()
