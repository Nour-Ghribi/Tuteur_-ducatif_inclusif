"""The in-process adapters against the GenAI module's real output schema (via ``FakeTutor``)."""

import pytest

pytest.importorskip(
    "tuteur.schemas", reason="install the GenAI module: pip install -e <repo root> --no-deps"
)

from tutor_agentic.assets import AssetRegistry
from tutor_agentic.errors import AdapterRejected, AdapterTimeout, MalformedResponse
from tutor_agentic.integrations.contracts import (
    AnswerEvaluationRequest,
    ContextPassage,
    GenerationRequest,
    RemediationInput,
    RetrievalRequest,
)
from tutor_agentic.integrations.tuteur_backend import (
    TuteurAnswerEvaluationAdapter,
    TuteurGenerationAdapter,
    TuteurRetrievalAdapter,
)
from tutor_agentic.schemas.common import Difficulty
from tutor_agentic.schemas.content import GenerationTask

from .fake_tutor import FakeLLM, FakeTutor


@pytest.fixture
def tutor() -> FakeTutor:
    return FakeTutor()


@pytest.fixture
def generation(tutor, adapter_kwargs) -> TuteurGenerationAdapter:
    return TuteurGenerationAdapter(tutor, **adapter_kwargs)


def request(task, **kw) -> GenerationRequest:
    return GenerationRequest(task=task, topic="photosynthèse", **kw)


class TestGeneration:
    async def test_quiz_is_converted_to_item_types_with_answer_keys(self, generation, tutor):
        response = await generation.generate(
            request(GenerationTask.QUIZ, n_items=2, difficulty=Difficulty.HARD)
        )
        mcq, tf = response.content.items
        assert (mcq.item_type, [o.option_id for o in mcq.options], mcq.correct_option_id) == (
            "mcq",
            ["a", "b", "c", "d"],
            "b",
        )
        assert (
            mcq.options[1].text == "Chlorophylle"
        )  # correct_option_id points at the answer's text
        assert (tf.item_type, tf.correct_option_id, [o.text for o in tf.options]) == (
            "true_false",
            "true",
            ["Vrai", "Faux"],
        )
        assert (
            mcq.skill == "Pigments"
            and mcq.source_pages == [1]
            and mcq.difficulty is Difficulty.MEDIUM
        )
        assert response.pages_used == [1, 2]
        kind, args = tutor.calls[0]
        assert (
            kind == "quiz"
            and args["difficulty"] == "difficile"
            and args["types"] == ("qcm", "vrai_faux")
        )

    async def test_flashcards_use_the_flashcard_item_type(self, generation, tutor):
        response = await generation.generate(request(GenerationTask.FLASHCARDS, n_items=3))
        assert response.content.kind == "flashcards" and len(response.content.cards) == 3
        assert tutor.calls[0][1]["types"] == ("flashcard",)

    async def test_explanation_reports_pages_and_removed_citations(self, generation, tutor):
        response = await generation.generate(
            request(GenerationTask.EXPLANATION, learner_request="Explique simplement")
        )
        assert [s.body[:5] for s in response.content.sections] == ["La ch", "Elle "]
        assert response.pages_used == [1, 2] and response.invalid_citations == [7]
        assert response.prompt_version == "answer@v3"
        assert tutor.calls[0][1]["question"] == "photosynthèse — Explique simplement"

    async def test_reading_level_is_forwarded(self, generation, tutor):
        from tutor_agentic.integrations.contracts import GenerationPreferences

        await generation.generate(
            request(
                GenerationTask.EXPLANATION,
                preferences=GenerationPreferences(reading_level="simplified"),
            )
        )
        assert tutor.calls[0][1]["reading_level"] == "simplifie"

    async def test_remediation_keeps_the_diagnostic_as_a_hypothesis_field(self, generation, tutor):
        response = await generation.generate(
            request(
                GenerationTask.REMEDIATION,
                remediation=RemediationInput(
                    question="Que rejette la photosynthèse ?",
                    student_answer="du CO2",
                    correct_answer="du dioxygène",
                    history=["Produits: erreur"],
                ),
            )
        )
        content = response.content
        assert content.diagnostic.startswith("Tu as peut-être")
        assert (
            content.exercise.items[0].item_type == "short_answer"
        )  # flashcard item -> graded free text
        assert content.exercise.items[0].reference_answer == "du dioxygène"
        assert tutor.calls[0][1]["history"] == ["Produits: erreur"]

    @pytest.mark.parametrize(
        "task",
        [
            GenerationTask.CONCEPT_MAP,
            GenerationTask.STEPS,
            GenerationTask.COMPARISON,
            GenerationTask.CONCEPT_CARDS,
        ],
    )
    async def test_added_formats_go_through_the_module_llm(self, generation, tutor, task):
        context = [
            ContextPassage(passage_id="c0", page=1, text="La chlorophylle capte la lumière.")
        ]
        response = await generation.generate(request(task, context=context))
        assert response.content.kind == task.value
        system, user, _ = tutor.llm.calls[0]
        assert (
            "=== PASSAGE 1 — page 1 ===" in user and "DONNÉES" in system
        )  # untrusted-data framing
        assert response.pages_used == [1]

    async def test_critic_feedback_reaches_the_prompt(self, generation, tutor):
        await generation.generate(
            request(
                GenerationTask.STEPS,
                critic_feedback=["content_kind_mismatch"],
                context=[ContextPassage(passage_id="c0", page=1, text="Texte.")],
            )
        )
        assert "content_kind_mismatch" in tutor.llm.calls[0][1]

    async def test_malformed_llm_output_for_added_formats_is_a_contract_violation(
        self, adapter_kwargs
    ):
        bad_map = {
            "kind": "concept_map",
            "title": "t",
            "central_node_id": "ghost",
            "nodes": [{"node_id": "a", "label": "A"}, {"node_id": "b", "label": "B"}],
        }
        tutor = FakeTutor(FakeLLM({"ConceptMapContent": bad_map}))
        adapter = TuteurGenerationAdapter(tutor, **adapter_kwargs)
        with pytest.raises(MalformedResponse):
            await adapter.generate(request(GenerationTask.CONCEPT_MAP))
        assert len(tutor.llm.calls) == 1  # not retried: retrying a bad contract changes nothing

    async def test_no_passage_is_a_rejection_not_a_retry(self, generation, tutor):
        tutor.fail_with = ValueError("Aucun passage trouvé dans la base pour générer le quiz.")
        with pytest.raises(AdapterRejected):
            await generation.generate(request(GenerationTask.QUIZ))
        assert len(tutor.calls) == 1

    async def test_llm_timeout_is_retried_then_reported(self, generation, tutor):
        class APITimeoutError(Exception):  # same class name as openai's
            pass

        tutor.fail_with = APITimeoutError()
        with pytest.raises(AdapterTimeout):
            await generation.generate(request(GenerationTask.QUIZ))
        assert len(tutor.calls) == 3  # 1 + max_retries


class TestRetrieval:
    def retrieval(self, tutor, adapter_kwargs, tmp_path) -> TuteurRetrievalAdapter:
        return TuteurRetrievalAdapter(tutor, AssetRegistry(), tmp_path, **adapter_kwargs)

    async def test_search_is_scoped_to_the_course_document(self, tutor, adapter_kwargs, tmp_path):
        adapter = self.retrieval(tutor, adapter_kwargs, tmp_path)
        result = await adapter.retrieve(
            RetrievalRequest(query="photosynthèse dioxygène", course_id="doc1")
        )
        assert {c.source.doc_id for c in result.chunks} == {"doc1"}
        assert result.chunks[0].source.page == 2 and result.simulated is False
        none = await adapter.retrieve(RetrievalRequest(query="photosynthèse", course_id="unknown"))
        assert none.chunks == []

    async def test_extracted_images_become_opaque_asset_ids(self, tutor, adapter_kwargs, tmp_path):
        (tmp_path / "doc1").mkdir()
        (tmp_path / "doc1" / "p1_img0.png").write_bytes(b"png")
        assets = AssetRegistry()
        adapter = TuteurRetrievalAdapter(tutor, assets, tmp_path, **adapter_kwargs)
        result = await adapter.retrieve(
            RetrievalRequest(query="chlorophylle lumière", course_id="doc1")
        )
        refs = result.chunks[0].image_refs
        assert len(refs) == 1 and refs[0].startswith("img-")
        assert assets.get(refs[0]).path.name == "p1_img0.png"
        assert str(tmp_path) not in result.model_dump_json()  # no file path leaves the backend


class TestGrader:
    async def test_open_answers_are_graded_by_the_llm(self, tutor, adapter_kwargs):
        grader = TuteurAnswerEvaluationAdapter(tutor, **adapter_kwargs)
        result = await grader.evaluate(
            AnswerEvaluationRequest(
                question_prompt="Que consomme la respiration ?",
                reference_answer="du dioxygène",
                student_answer="de l'oxygène",
            )
        )
        assert result.is_correct and result.score == 0.9 and result.simulated is False
        system, user, schema = tutor.llm.calls[0]
        assert schema == "GradeResult" and "DONNÉE" in system and "de l'oxygène" in user


class TestFullLoopOnModuleAdapters:
    """quiz -> wrong answer -> remediation -> free-text answer, all through the in-process adapters."""

    @pytest.fixture
    def service(self, make_service, tutor, adapter_kwargs, tmp_path):
        return make_service(
            retrieval=TuteurRetrievalAdapter(tutor, AssetRegistry(), tmp_path, **adapter_kwargs),
            generation=TuteurGenerationAdapter(tutor, **adapter_kwargs),
            evaluation=TuteurAnswerEvaluationAdapter(tutor, **adapter_kwargs),
        )

    async def test_loop(self, service, student, tutor):
        from tutor_agentic.schemas.common import PresentationFormat
        from tutor_agentic.schemas.requests import (
            AnswerSubmission,
            ExperienceRequest,
            StudentAnswer,
        )

        quiz = await service.create_experience(
            student,
            ExperienceRequest(
                message="Quiz me",
                course_id="doc1",
                topic="photosynthèse chlorophylle dioxygène lumière",
                requested_format=PresentationFormat.QUIZ,
            ),
        )
        verification = quiz.ui.meta.verification
        assert (
            quiz.status.value == "ok"
            and verification.passed
            and "grounding_pages" in verification.checks_run
        )
        assert quiz.ui.meta.simulated is False  # nothing here is a mock service
        first = quiz.ui.blocks[0].questions[0]
        assert "correct_option_id" not in quiz.model_dump_json()

        wrong = await service.submit_answer(
            student,
            AnswerSubmission(
                question_id=first.question_id, answer=StudentAnswer(selected_option_id="a")
            ),
        )
        kinds = [b.type for b in wrong.ui.blocks]
        assert (
            kinds[0] == "quiz_feedback" and "quiz" in kinds and kinds[-1] == "recommendation_card"
        )
        assert wrong.ui.meta.verification.passed
        remediation_call = next(args for kind, args in tutor.calls if kind == "remediate")
        assert remediation_call["student_answer"] == "Carotène"  # the text of the option chosen
        assert remediation_call["correct_answer"] == "Chlorophylle"

        exercise = next(b for b in wrong.ui.blocks if b.type == "quiz").questions[0]
        assert exercise.item_type == "short_answer" and exercise.options == []
        graded = await service.submit_answer(
            student,
            AnswerSubmission(
                question_id=exercise.question_id, answer=StudentAnswer(text="de l'oxygène")
            ),
        )
        assert graded.ui.blocks[0].is_correct and graded.ui.blocks[0].score == 0.9
        assert tutor.llm.calls[-1][2] == "GradeResult"
