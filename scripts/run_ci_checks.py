"""Reproduce the main GitHub Actions checks on a developer machine."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_NAME = "tuteur-inclusif-api:ci"


def run(command: list[str]) -> None:
    """Run one check from the repository root and stop on failure."""
    print(f"\n> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Run only the Python quality checks.",
    )
    args = parser.parse_args()

    python = sys.executable
    run([python, "-m", "ruff", "check", "app", "orchestration", "scripts", "tests"])
    run([python, "-m", "pytest", "-q"])
    run([python, "-m", "pip", "check"])

    if not args.skip_docker:
        run(["docker", "build", "--tag", IMAGE_NAME, "."])
        run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "python",
                IMAGE_NAME,
                "-c",
                "from app.main import app; assert app.title; print(app.title)",
            ]
        )

    print("\nAll requested CI checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
