"""The learning-session loop: quiz -> answer -> grade -> remediation -> RL, with server-side history."""

from typing import ClassVar

import pytest
from pydantic import ValidationError

from tutor_agentic.integrations.contracts import RecommendationServiceResponse
from tutor_agentic.integrations.mocks import MockContentGenerationAdapter, MockRecommendationAdapter
from tutor_agentic.schemas.common import PresentationFormat
from tutor_agentic.schemas.requests import (
    AnswerSubmission,
    ExperienceRequest,
    RecommendationRequest,
    StudentAnswer,
)
from tutor_agentic.schemas.responses import ResponseStatus
from tutor_agentic.telemetry import VERIFICATION_RESULT

COURSE = "demo-bio-101"


def quiz_request(**kw) -> ExperienceRequest:
    return ExperienceRequest(
        message="Quiz me",
        course_id=COURSE,
        topic="photosynthèse",
        requested_format=PresentationFormat.QUIZ,
        **kw,
    )


def wrong(question_id: str) -> AnswerSubmission:
    return AnswerSubmission(question_id=question_id, answer=StudentAnswer(selected_option_id="b"))


def block(response, kind: str):
    return [b for b in response.ui.blocks if b.type == kind]


def codes(response) -> list[str]:
    return [b.message_code for b in block(response, "callout")]


class TestHypothesisWording:
    async def test_first_error_is_a_tentative_hypothesis_then_recurring(
        self, make_service, student
    ):
        service = make_service()
        quiz = await service.create_experience(student, quiz_request())
        ids = [q.question_id for q in quiz.ui.blocks[0].questions]

        first = await service.submit_answer(student, wrong(ids[0]))
        assert "misconception_hypothesis" in codes(first)
        assert "misconception_hypothesis_recurring" not in codes(first)
        # the diagnostic text is framed by a code the UI localizes as "possible confusion"
        assert next(
            b.text for b in block(first, "callout") if b.message_code == "misconception_hypothesis"
        )

        second = await service.submit_answer(
            student, wrong(ids[1])
        )  # same competence (mock: no skill)
        assert "misconception_hypothesis_recurring" in codes(second)

    async def test_observed_errors_and_hypothesis_are_separate_blocks(self, make_service, student):
        service = make_service()
        quiz = await service.create_experience(student, quiz_request())
        response = await service.submit_answer(
            student, wrong(quiz.ui.blocks[0].questions[0].question_id)
        )
        feedback = block(response, "quiz_feedback")[0]
        assert feedback.observed_errors == ["selected_incorrect_option"]
        assert feedback.type != "callout"


class TestHistory:
    async def test_graded_answers_feed_remediation_and_rl(
        self, make_service, student, adapter_kwargs
    ):
        class SpyRL(MockRecommendationAdapter):
            seen: ClassVar[list] = []

            async def recommend(self, request):
                self.seen.append(request.features)
                return await super().recommend(request)

        spy_generation = MockContentGenerationAdapter(**adapter_kwargs)
        rl = SpyRL(**adapter_kwargs)
        service = make_service(recommendation=rl, generation=spy_generation)
        quiz = await service.create_experience(student, quiz_request())
        ids = [q.question_id for q in quiz.ui.blocks[0].questions]

        await service.submit_answer(student, wrong(ids[0]))
        await service.submit_answer(student, wrong(ids[1]))

        remediations = [r for r in spy_generation.requests if r.remediation]
        assert remediations[0].remediation.history == []  # nothing known before the first answer
        assert len(remediations[1].remediation.history) == 1  # first error is passed on the second
        assert rl.seen[1].recent_scores == [
            0.0,
            0.0,
        ]  # derived server-side, includes the current answer
        assert rl.seen[1].last_outcome == "incorrect"

    async def test_unanswered_or_ungraded_requests_do_not_enter_history(
        self, make_service, student
    ):
        service = make_service()
        await service.create_experience(student, quiz_request())
        assert (
            service._history.snapshot(
                student.subject_ref, topic=None, competence=None
            ).attempts_total
            == 0
        )

    async def test_progress_reflects_recorded_attempts(self, make_service, student):
        service = make_service()
        assert service.progress(student).ui.blocks[0].message_code == "no_progress_yet"
        quiz = await service.create_experience(student, quiz_request())
        await service.submit_answer(
            student,
            AnswerSubmission(
                question_id=quiz.ui.blocks[0].questions[0].question_id,
                answer=StudentAnswer(selected_option_id="a"),
            ),
        )
        progress = service.progress(student)
        assert [b.type for b in progress.ui.blocks] == ["metric_grid", "progress"]
        assert progress.ui.blocks[1].value == 1.0

    async def test_learners_do_not_share_history(self, make_service, student):
        service = make_service()
        quiz = await service.create_experience(student, quiz_request())
        await service.submit_answer(student, wrong(quiz.ui.blocks[0].questions[0].question_id))
        other = student.model_copy(update={"subject_ref": "student-dev-2"})
        assert service.progress(other).ui.blocks[0].message_code == "no_progress_yet"


class TestGroundingChecks:
    def quiz_with(self, pages):
        item = {
            "item_id": "q1",
            "item_type": "true_false",
            "prompt": "?",
            "options": [{"option_id": "t", "text": "Vrai"}, {"option_id": "f", "text": "Faux"}],
            "correct_option_id": "t",
            "source_pages": pages,
        }
        return {"kind": "quiz", "title": "t", "items": [item]}

    async def test_pages_outside_the_retrieved_passages_are_rejected(
        self, make_service, student, adapter_kwargs, sink
    ):
        generator = MockContentGenerationAdapter(
            content_override=self.quiz_with([99]), **adapter_kwargs
        )
        response = await make_service(generation=generator).create_experience(
            student, quiz_request().model_copy(update={"message": "Génère 1 question"})
        )
        assert generator.requests[1].critic_feedback == ["source_page_outside_context"]
        assert response.status is ResponseStatus.FAILED
        assert response.ui.meta.verification.issues == ["source_page_outside_context"]
        assert "grounding_pages" in response.ui.meta.verification.checks_run
        assert len(sink.named(VERIFICATION_RESULT)) == 2

    async def test_missing_source_pages_is_a_note_not_a_failure(
        self, make_service, student, adapter_kwargs
    ):
        generator = MockContentGenerationAdapter(
            content_override=self.quiz_with([]), **adapter_kwargs
        )
        response = await make_service(generation=generator).create_experience(
            student, quiz_request().model_copy(update={"message": "Génère 1 question"})
        )
        assert response.status is ResponseStatus.OK  # notes never degrade the response
        assert response.ui.meta.verification.notes == ["missing_source_pages"]
        assert "missing_source_pages" in response.ui.meta.warnings

    async def test_question_ids_are_unique_per_request(self, make_service, student):
        service = make_service()
        a = await service.create_experience(student, quiz_request())
        b = await service.create_experience(student, quiz_request())
        ids = {q.question_id for r in (a, b) for q in r.ui.blocks[0].questions}
        assert len(ids) == 10


class TestRecommendationGuards:
    async def test_the_client_cannot_supply_performance(self):
        with pytest.raises(ValidationError):
            RecommendationRequest(course_id=COURSE, topic="t", performance={"recent_scores": [1.0]})

    async def test_rl_choice_must_be_an_offered_activity(
        self, make_service, student, adapter_kwargs
    ):
        class Rogue(MockRecommendationAdapter):
            async def recommend(self, request):
                return RecommendationServiceResponse(
                    recommendation_id="r1",
                    activity_type="quiz",
                    difficulty="hard",
                    topic="not offered",
                )

        response = await make_service(recommendation=Rogue(**adapter_kwargs)).recommend_next(
            student, RecommendationRequest(course_id=COURSE, topic="photosynthèse")
        )
        assert response.status is ResponseStatus.FAILED


class TestSingleAttempt:
    async def test_a_graded_question_cannot_be_answered_again(self, make_service, student):
        """The feedback reveals the key; resubmitting it must not turn a failure into a success."""
        from tutor_agentic.errors import NotFound

        service = make_service()
        quiz = await service.create_experience(student, quiz_request())
        question_id = quiz.ui.blocks[0].questions[0].question_id
        first = await service.submit_answer(student, wrong(question_id))
        assert first.ui.blocks[0].is_correct is False
        with pytest.raises(NotFound):
            await service.submit_answer(
                student,
                AnswerSubmission(
                    question_id=question_id, answer=StudentAnswer(selected_option_id="a")
                ),
            )
        history = service._history.snapshot(student.subject_ref, topic=None, competence=None)
        assert history.attempts_total == 1 and history.recent_scores == [0.0]

    async def test_an_ungraded_attempt_can_be_retried(self, make_service, student, adapter_kwargs):
        from tutor_agentic.integrations.mocks import FaultInjector, MockAnswerEvaluationAdapter

        evaluation = MockAnswerEvaluationAdapter(
            faults=FaultInjector("unavailable", times=3), **adapter_kwargs
        )
        service = make_service(
            evaluation=evaluation,
            generation=MockContentGenerationAdapter(
                content_override={
                    "kind": "quiz",
                    "title": "t",
                    "items": [
                        {
                            "item_id": "q1",
                            "item_type": "short_answer",
                            "prompt": "?",
                            "reference_answer": "r",
                        }
                    ],
                },
                **adapter_kwargs,
            ),
        )
        quiz = await service.create_experience(
            student, quiz_request().model_copy(update={"message": "1 question"})
        )
        question_id = quiz.ui.blocks[0].questions[0].question_id
        submission = AnswerSubmission(question_id=question_id, answer=StudentAnswer(text="r"))
        failed = await service.submit_answer(student, submission)
        assert (
            failed.status is ResponseStatus.FAILED
        )  # grader down: nothing graded, nothing consumed
        retried = await service.submit_answer(student, submission)
        assert retried.ui.blocks[0].type == "quiz_feedback"
