"""Génère du trafic local, y compris des validations 422, pour les dashboards."""

import argparse
import time

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--delay", type=float, default=0.05)
    return parser.parse_args()


def generate_traffic(base_url: str, cycles: int, delay: float) -> dict[int, int]:
    requests_to_send = (
        ("GET", "/health", None),
        (
            "POST",
            "/generate-quiz",
            {
                "subject": "Mathématiques",
                "topic": "Fractions",
                "difficulty": "facile",
                "number_of_questions": 2,
            },
        ),
        (
            "POST",
            "/student-answer",
            {
                "quiz_id": "quiz-trafic-synthetique",
                "question_id": 1,
                "answer": "Choix B",
                "expected_answer": "Choix A",
            },
        ),
        (
            "POST",
            "/next-activity",
            {"performance_score": 0.65, "attempts": 2, "current_topic": "Fractions"},
        ),
        (
            "POST",
            "/next-activity",
            {"performance_score": 1.5, "attempts": 1, "current_topic": "Fractions"},
        ),
    )
    statuses: dict[int, int] = {}

    with httpx.Client(base_url=base_url, timeout=10) as client:
        for _ in range(cycles):
            for method, path, payload in requests_to_send:
                response = client.request(method, path, json=payload)
                statuses[response.status_code] = statuses.get(response.status_code, 0) + 1
                time.sleep(delay)

    return statuses


if __name__ == "__main__":
    arguments = parse_args()
    result = generate_traffic(arguments.base_url, arguments.cycles, arguments.delay)
    print(f"Trafic généré : {sum(result.values())} requêtes")
    print(f"Répartition des statuts : {dict(sorted(result.items()))}")
