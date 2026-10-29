"""Graph routing and failure-handling tests (all services mocked, results simulated)."""

from datetime import date

import pytest

from tutor_agentic.errors import NotFound
from tutor_agentic.graph import edges
from tutor_agentic.history import Attempt
from tutor_agentic.integrations.contracts import RecommendationServiceResponse
from tutor_agentic.integrations.mocks import (
    FaultInjector,
    MockContentGenerationAdapter,
    MockLearningRecordsAdapter,
    MockRecommendationAdapter,
    MockRetrievalAdapter,
)
from tutor_agentic.schemas.common import AccessibilityPreferences, PresentationFormat, Workflow
from tutor_agentic.schemas.requests import (
    AnswerSubmission,
    ExperienceRequest,
    PreviousActivity,
    RecommendationRequest,
    StudentAnswer,
    TeacherReportRequest,
)
from tutor_agentic.schemas.responses import ResponseStatus
from tutor_agentic.state import NodeError, WorkflowPlan
from tutor_agentic.telemetry import VERIFICATION_RESULT, WORKFLOW_COMPLETED

COURSE = "demo-bio-101"


def experience(message: str, **kwargs) -> ExperienceRequest:
    return ExperienceRequest(message=message, course_id=COURSE, topic="photosynthèse", **kwargs)


def block_types(response) -> list[str]:
    return [b.type for b in response.ui.blocks]


@pytest.mark.parametrize(
    ("message", "intent", "expected_block"),
    [
        ("Explain this chapter simply.", "explain", "heading"),
        ("Generate five questions about this topic.", "quiz", "quiz"),
        ("Give me flashcards.", "flashcards", "flashcard_deck"),
        ("Create a mind map.", "concept_map", "concept_map"),
        ("Guide me step by step", "steps", "steps"),
        ("Show me the key concepts", "concept_cards", "concept_cards"),
        ("Compare these concepts", "comparison", "comparison_table"),
    ],
)
async def test_experience_intent_selects_presentation(
    make_service, student, adapter_kwargs, message, intent, expected_block
):
    rl = MockRecommendationAdapter(**adapter_kwargs)
    service = make_service(recommendation=rl)
    response = await service.create_experience(student, experience(message))
    assert response.intent == intent
    assert response.status is ResponseStatus.OK
    assert expected_block in block_types(response)
    assert rl.calls == 0  # conditional routing: no RL call for a plain content request
    meta = response.ui.meta
    assert meta.simulated and set(meta.simulated_services) == {"genai", "rag"}
    assert meta.grounding == "context_provided" and meta.sources
    assert meta.verification.checks_run[0] == "structure" and meta.verification.passed


async def test_quiz_count_and_answer_keys_never_reach_the_client(make_service, student):
    response = await make_service().create_experience(
        student, experience("Génère 3 questions sur la photosynthèse")
    )
    quiz = response.ui.blocks[0]
    assert len(quiz.questions) == 3
    dumped = response.model_dump_json()
    assert "correct_option_id" not in dumped and "reference_answer" not in dumped


async def test_new_exercise_calls_rl_and_returns_one_item(make_service, student, adapter_kwargs):
    rl = MockRecommendationAdapter(**adapter_kwargs)
    response = await make_service(recommendation=rl).create_experience(
        student,
        experience(
            "Give me another exercise because I got the previous one wrong.",
            previous_activity=PreviousActivity(activity_id="q-old", outcome="incorrect"),
        ),
    )
    assert response.intent == "new_exercise"
    assert block_types(response) == ["quiz", "recommendation_card"]
    assert len(response.ui.blocks[0].questions) == 1
    assert rl.calls == 1
    assert "rl" in response.ui.meta.simulated_services


async def test_preferences_are_forwarded_to_generation(make_service, student, adapter_kwargs):
    generator = MockContentGenerationAdapter(**adapter_kwargs)
    prefs = AccessibilityPreferences(simplified_language=True, short_segments=True)
    await make_service(generation=generator).create_experience(
        student, experience("Explain", preferences=prefs, language="en")
    )
    sent = generator.requests[0].preferences
    assert (sent.reading_level, sent.max_segment_chars, sent.language) == ("simplified", 400, "en")


async def test_course_passages_are_sent_as_untrusted_context(make_service, student, adapter_kwargs):
    generator = MockContentGenerationAdapter(**adapter_kwargs)
    await make_service(generation=generator).create_experience(student, experience("Explain"))
    request = generator.requests[0]
    assert request.context and all(p.trust == "untrusted" for p in request.context)


class TestDegradation:
    async def test_rag_outage_degrades_but_still_answers(
        self, make_service, student, adapter_kwargs
    ):
        rag = MockRetrievalAdapter(faults=FaultInjector("unavailable"), **adapter_kwargs)
        response = await make_service(retrieval=rag).create_experience(
            student, experience("Explain")
        )
        assert response.status is ResponseStatus.DEGRADED
        assert response.ui.meta.grounding == "no_context"
        assert "retrieval_unavailable" in response.ui.meta.warnings
        assert response.ui.meta.sources == []

    async def test_unknown_course_reports_missing_context(
        self, make_service, student, adapter_kwargs
    ):
        generator = MockContentGenerationAdapter(**adapter_kwargs)
        response = await make_service(generation=generator).create_experience(
            student, ExperienceRequest(message="Explain", course_id="unknown-course")
        )
        assert response.status is ResponseStatus.DEGRADED
        assert "no_context_found" in response.ui.meta.warnings
        # No passage: nothing is generated, and the learner is told the course has nothing on it.
        assert generator.calls == 0
        assert block_types(response) == ["callout"]
        assert response.ui.blocks[0].message_code == "no_course_content"

    async def test_generation_outage_returns_safe_fallback(
        self, make_service, student, adapter_kwargs
    ):
        generator = MockContentGenerationAdapter(faults=FaultInjector("timeout"), **adapter_kwargs)
        response = await make_service(generation=generator).create_experience(
            student, experience("Explain")
        )
        assert response.status is ResponseStatus.FAILED
        assert block_types(response) == ["fallback"]
        assert response.ui.blocks[0].reason_code == "generation_unavailable"
        assert response.ui.meta.fallback_used

    async def test_malformed_llm_output_returns_fallback(
        self, make_service, student, adapter_kwargs
    ):
        generator = MockContentGenerationAdapter(
            content_override={"kind": "quiz", "title": "t", "items": [{"prompt": "no key"}]},
            **adapter_kwargs,
        )
        response = await make_service(generation=generator).create_experience(
            student, experience("Quiz me")
        )
        assert response.status is ResponseStatus.FAILED
        assert generator.calls == 1  # malformed output is not retried at the transport level


class TestCriticLoop:
    async def test_wrong_format_is_regenerated_then_abandoned(
        self, make_service, student, adapter_kwargs, sink
    ):
        # The service keeps returning an explanation although flashcards were requested.
        generator = MockContentGenerationAdapter(
            content_override={"kind": "explanation", "title": "t", "sections": [{"body": "b"}]},
            **adapter_kwargs,
        )
        response = await make_service(generation=generator).create_experience(
            student, experience("Give me flashcards")
        )
        assert len(generator.requests) == 2  # bounded by max_generation_attempts
        assert generator.requests[1].critic_feedback == ["content_kind_mismatch"]
        assert response.status is ResponseStatus.FAILED
        assert response.ui.blocks[0].reason_code == "content_verification_failed"
        assert response.ui.meta.verification.passed is False
        assert [e.attributes["passed"] for e in sink.named(VERIFICATION_RESULT)] == [False, False]

    async def test_item_count_mismatch_is_detected(self, make_service, student, adapter_kwargs):
        one_item_quiz = {
            "kind": "quiz",
            "title": "t",
            "items": [
                {
                    "item_id": "q1",
                    "item_type": "true_false",
                    "prompt": "?",
                    "options": [
                        {"option_id": "t", "text": "Vrai"},
                        {"option_id": "f", "text": "Faux"},
                    ],
                    "correct_option_id": "t",
                }
            ],
        }
        generator = MockContentGenerationAdapter(content_override=one_item_quiz, **adapter_kwargs)
        response = await make_service(generation=generator).create_experience(
            student, experience("Generate five questions")
        )
        assert response.ui.meta.verification.issues == ["item_count_mismatch"]


class TestAnswerWorkflow:
    async def _issue_quiz(self, service, student):
        response = await service.create_experience(
            student, experience("Quiz me", requested_format=PresentationFormat.QUIZ)
        )
        return response.ui.blocks[0].questions[0].question_id

    async def test_correct_answer_skips_remediation(self, make_service, student, adapter_kwargs):
        generator = MockContentGenerationAdapter(**adapter_kwargs)
        service = make_service(generation=generator)
        question_id = await self._issue_quiz(service, student)
        response = await service.submit_answer(
            student,
            AnswerSubmission(
                question_id=question_id,
                answer=StudentAnswer(selected_option_id="a"),
                request_recommendation=False,
            ),
        )
        assert block_types(response) == ["quiz_feedback"]
        feedback = response.ui.blocks[0]
        assert feedback.is_correct and feedback.score == 1.0
        assert len(generator.requests) == 1  # only the original quiz

    async def test_wrong_answer_gets_remediation_and_recommendation(self, make_service, student):
        service = make_service()
        question_id = await self._issue_quiz(service, student)
        response = await service.submit_answer(
            student,
            AnswerSubmission(question_id=question_id, answer=StudentAnswer(selected_option_id="b")),
        )
        types = block_types(response)
        assert types[0] == "quiz_feedback" and types[-1] == "recommendation_card"
        assert "quiz" in types  # remedial exercise
        feedback = response.ui.blocks[0]
        assert not feedback.is_correct
        # Only what was observed; no misconception is claimed (diagnosis arrives in Phase 3).
        assert feedback.observed_errors == ["selected_incorrect_option"]

    async def test_remedial_question_can_be_answered_next(self, make_service, student):
        service = make_service()
        question_id = await self._issue_quiz(service, student)
        wrong = await service.submit_answer(
            student,
            AnswerSubmission(question_id=question_id, answer=StudentAnswer(selected_option_id="b")),
        )
        remedial = next(b for b in wrong.ui.blocks if b.type == "quiz").questions[0]
        assert remedial.question_id != question_id
        again = await service.submit_answer(
            student,
            AnswerSubmission(
                question_id=remedial.question_id, answer=StudentAnswer(selected_option_id="a")
            ),
        )
        assert again.ui.blocks[0].is_correct

    async def test_remediation_failure_keeps_feedback(self, make_service, student, adapter_kwargs):
        generator = MockContentGenerationAdapter(**adapter_kwargs)
        service = make_service(generation=generator)
        question_id = await self._issue_quiz(service, student)
        generator.faults = FaultInjector("unavailable")
        response = await service.submit_answer(
            student,
            AnswerSubmission(
                question_id=question_id,
                answer=StudentAnswer(selected_option_id="b"),
                request_recommendation=False,
            ),
        )
        assert response.status is ResponseStatus.DEGRADED
        assert block_types(response) == ["quiz_feedback"]
        assert "generation_unavailable" in response.ui.meta.warnings

    async def test_rl_outage_during_answer_is_not_fatal(
        self, make_service, student, adapter_kwargs
    ):
        rl = MockRecommendationAdapter(faults=FaultInjector("unavailable"), **adapter_kwargs)
        service = make_service(recommendation=rl)
        question_id = await self._issue_quiz(service, student)
        response = await service.submit_answer(
            student,
            AnswerSubmission(question_id=question_id, answer=StudentAnswer(selected_option_id="a")),
        )
        assert response.status is ResponseStatus.DEGRADED
        assert block_types(response) == ["quiz_feedback"]

    async def test_questions_are_scoped_to_their_learner(self, make_service, student):
        service = make_service()
        question_id = await self._issue_quiz(service, student)
        other = student.model_copy(update={"subject_ref": "student-dev-2"})
        with pytest.raises(NotFound):
            await service.submit_answer(
                other,
                AnswerSubmission(
                    question_id=question_id, answer=StudentAnswer(selected_option_id="a")
                ),
            )

    async def test_wrong_answer_format_returns_fallback(self, make_service, student):
        service = make_service()
        question_id = await self._issue_quiz(service, student)
        response = await service.submit_answer(
            student, AnswerSubmission(question_id=question_id, answer=StudentAnswer(text="a"))
        )
        assert response.status is ResponseStatus.FAILED
        assert response.ui.blocks[0].reason_code == "invalid_answer_format"


class TestLearningPath:
    def request(self) -> RecommendationRequest:
        return RecommendationRequest(course_id=COURSE, topic="photosynthèse")

    async def test_low_scores_get_revision(self, make_service, student):
        service = make_service()
        for score in (0.2, 0.3):  # history is server-side: the client cannot supply scores
            service._history.record(
                student.subject_ref,
                Attempt(topic="photosynthèse", correct=False, score=score),
            )
        response = await service.recommend_next(student, self.request())
        card = response.ui.blocks[0]
        assert card.type == "recommendation_card"
        assert (card.activity_type.value, card.difficulty.value) == ("revision", "easy")

    async def test_rl_outage_is_fatal_for_learning_path(
        self, make_service, student, adapter_kwargs
    ):
        rl = MockRecommendationAdapter(faults=FaultInjector("unavailable"), **adapter_kwargs)
        response = await make_service(recommendation=rl).recommend_next(student, self.request())
        assert response.status is ResponseStatus.FAILED
        assert response.ui.blocks[0].reason_code == "recommendation_unavailable"

    async def test_unavailable_recommendation_is_rejected(
        self, make_service, student, adapter_kwargs
    ):
        class RogueRL(MockRecommendationAdapter):
            async def recommend(self, request):
                return RecommendationServiceResponse(
                    recommendation_id="r1",
                    activity_type="quiz",
                    difficulty="hard",
                    topic="other topic",
                )

        response = await make_service(recommendation=RogueRL(**adapter_kwargs)).recommend_next(
            student, self.request()
        )
        assert response.status is ResponseStatus.FAILED
        assert response.ui.blocks[0].reason_code == "recommendation_unavailable"
        assert "recommendation_not_available" in response.ui.meta.warnings

    async def test_outcome_is_forwarded_to_rl(self, make_service, student, adapter_kwargs):
        from tutor_agentic.schemas.requests import ActivityOutcome

        rl = MockRecommendationAdapter(**adapter_kwargs)
        service = make_service(recommendation=rl)
        response = await service.recommend_next(student, self.request())
        rec_id = response.ui.blocks[0].recommendation_id
        ack = await service.record_outcome(
            student, rec_id, ActivityOutcome(completed=True, score=0.8)
        )
        assert ack.accepted and ack.simulated
        assert rl.outcomes[0].student_ref == student.subject_ref
        with pytest.raises(NotFound):
            await service.record_outcome(student, "rec-unknown", ActivityOutcome(completed=True))


class TestTeacherReport:
    def request(self, class_id="class-demo-a") -> TeacherReportRequest:
        return TeacherReportRequest(
            class_id=class_id, period_start=date(2026, 9, 1), period_end=date(2026, 10, 1)
        )

    async def test_report_contains_aggregates_and_is_marked_simulated(self, make_service, teacher):
        response = await make_service().teacher_report(teacher, self.request())
        types = block_types(response)
        assert types[:2] == ["metric_grid", "bar_chart"] and "text" in types
        assert response.ui.meta.simulated
        assert "learning_records" in response.ui.meta.simulated_services
        assert response.ui.meta.grounding == "not_applicable"

    async def test_records_outage_returns_fallback(self, make_service, teacher, adapter_kwargs):
        records = MockLearningRecordsAdapter(faults=FaultInjector("unavailable"), **adapter_kwargs)
        response = await make_service(learning_records=records).teacher_report(
            teacher, self.request()
        )
        assert response.ui.blocks[0].reason_code == "report_data_unavailable"


class TestEdges:
    def test_fatal_error_routes_to_recovery(self):
        state = {
            "workflow": Workflow.EXPERIENCE,
            "errors": [NodeError(node="intake", code="x", fatal=True)],
        }
        assert edges.after_intake(state) == "recover"

    @pytest.mark.parametrize(
        ("workflow", "node"),
        [
            (Workflow.EXPERIENCE, "plan_experience"),
            (Workflow.ANSWER, "evaluate_answer"),
            (Workflow.LEARNING_PATH, "recommend_activity"),
            (Workflow.TEACHER_REPORT, "load_report_data"),
        ],
    )
    def test_workflow_entry(self, workflow, node):
        assert edges.after_intake({"workflow": workflow, "errors": []}) == node

    def test_content_without_recommendation_goes_to_ui(self):
        plan = WorkflowPlan(task=None, topic="t", retrieval_query="", needs_recommendation=False)
        assert edges.after_content({"plan": plan, "errors": []}) == "attach_images"


async def test_graph_level_teacher_guard(make_service, student):
    """Even if the application check were bypassed, the graph refuses reports for students."""
    service = make_service()
    state = await service.graph.ainvoke(
        {
            "request_id": "r" * 32,
            "workflow": Workflow.TEACHER_REPORT,
            "actor_role": "student",
            "report_request": TestTeacherReport().request(),
            "warnings": [],
            "errors": [],
            "simulated_services": [],
        }
    )
    assert state["status"] is ResponseStatus.FAILED
    assert state["ui"].blocks[0].reason_code == "forbidden"


async def test_workflow_telemetry_has_no_learner_content(make_service, student, sink):
    await make_service().create_experience(student, experience("Explain la chlorophylle"))
    event = sink.named(WORKFLOW_COMPLETED)[-1]
    assert event.attributes["workflow"] == "experience"
    assert event.attributes["outcome"] == "ok"
    serialized = repr([e.attributes for e in sink.events])
    assert "chlorophylle" not in serialized and student.subject_ref not in serialized
