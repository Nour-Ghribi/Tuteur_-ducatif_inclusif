"""Logique métier déterministe utilisée avant l'intégration de RAG et RL réels."""

import hashlib

from app.mlflow_tracing import trace_quiz_generation
from app.schemas import (
    NextActivityRequest,
    NextActivityResponse,
    QuizQuestion,
    QuizRequest,
    QuizResponse,
    StudentAnswerRequest,
    StudentAnswerResponse,
)


def _accessibility_messages(needs: list[str]) -> list[str]:
    if not needs:
        return ["Format standard synthétique"]
    return [f"Support simulé prévu pour : {need.strip()}" for need in needs]


@trace_quiz_generation
def generate_mock_quiz(request: QuizRequest) -> QuizResponse:
    """Construit un quiz synthétique stable à partir de la requête."""
    quiz_key = f"{request.subject}|{request.topic}|{request.difficulty}"
    quiz_id = f"quiz-{hashlib.sha256(quiz_key.encode()).hexdigest()[:10]}"
    questions = [
        QuizQuestion(
            id=index,
            prompt=f"Question simulée {index} sur le thème « {request.topic} » ?",
            choices=[f"Choix {letter}" for letter in ("A", "B", "C")],
            correct_answer="Choix A",
        )
        for index in range(1, request.number_of_questions + 1)
    ]
    return QuizResponse(
        quiz_id=quiz_id,
        subject=request.subject,
        topic=request.topic,
        difficulty=request.difficulty,
        questions=questions,
        accessibility_support=_accessibility_messages(request.accessibility_needs),
        is_simulated=True,
    )


def correct_mock_answer(request: StudentAnswerRequest) -> StudentAnswerResponse:
    """Compare deux chaînes normalisées sans prétendre évaluer un élève réel."""
    is_correct = request.answer.strip().casefold() == request.expected_answer.strip().casefold()
    feedback = (
        "Bonne réponse dans cette simulation."
        if is_correct
        else "Réponse différente de la valeur attendue dans cette simulation."
    )
    return StudentAnswerResponse(
        quiz_id=request.quiz_id,
        question_id=request.question_id,
        is_correct=is_correct,
        score=1.0 if is_correct else 0.0,
        feedback=feedback,
        is_simulated=True,
    )


def choose_mock_activity(request: NextActivityRequest) -> NextActivityResponse:
    """Applique une politique à règles explicites en remplacement du futur agent RL."""
    if request.performance_score < 0.5:
        activity_type = "remediation"
        difficulty = "facile"
        reason = "Score synthétique inférieur à 0,5 : révision guidée proposée."
    elif request.performance_score < 0.8:
        activity_type = "practice"
        difficulty = "moyen"
        reason = "Score synthétique intermédiaire : entraînement supplémentaire proposé."
    else:
        activity_type = "challenge"
        difficulty = "difficile"
        reason = "Score synthétique supérieur ou égal à 0,8 : défi proposé."

    if request.attempts >= 3 and activity_type != "challenge":
        reason += " Plusieurs tentatives ont été signalées."

    return NextActivityResponse(
        activity_type=activity_type,
        difficulty=difficulty,
        reason=reason,
        topic=request.current_topic,
        accessibility_support=_accessibility_messages(request.accessibility_needs),
        policy="mock-rules-v1",
        is_simulated=True,
    )

