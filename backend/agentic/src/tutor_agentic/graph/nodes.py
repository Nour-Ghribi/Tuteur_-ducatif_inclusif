"""LangGraph nodes. Each returns a partial state update; none raises on dependency failure.

Only routing (intent), the critic loop and recovery make decisions; the other nodes are plain
service calls wrapped with typed error handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..config import Settings
from ..errors import AdapterError
from ..history import RECURRING_THRESHOLD, HistorySnapshot
from ..integrations.contracts import (
    ActivityOption,
    AnswerEvaluationRequest,
    ColorAdaptationRequest,
    ContextPassage,
    GenerationPreferences,
    GenerationRequest,
    ImageDescriptionRequest,
    LearnerFeatures,
    LearningSummariesRequest,
    RecommendationServiceRequest,
    RemediationInput,
    RetrievalRequest,
)
from ..integrations.convert import question_for
from ..integrations.registry import AdapterSet
from ..routing.intents import DEFAULT_ITEM_COUNT, INTENT_TO_TASK, Intent
from ..routing.router import IntentRouter
from ..schemas import ui
from ..schemas.common import (
    AccessibilityPreferences,
    ActivityType,
    ColorVisionDeficiency,
    Difficulty,
    Workflow,
)
from ..schemas.content import GenerationTask, QuizItem, ReportSummaryContent
from ..schemas.responses import ResponseStatus
from ..state import (
    AnswerEvaluation,
    GenerationOutcome,
    NodeError,
    RecommendationOutcome,
    TutorState,
    WorkflowPlan,
    has_fatal_error,
)
from ..telemetry import VERIFICATION_RESULT, Telemetry
from . import ui_planner
from .verification import verify

Update = dict[str, Any]
MAX_IMAGES = 2

# Fatal error -> localizable reason shown in the fallback block.
REASON_BY_NODE = {
    "generate_content": "generation_unavailable",
    "verify_content": "content_verification_failed",
    "recommend_activity": "recommendation_unavailable",
    "load_report_data": "report_data_unavailable",
}


@dataclass
class GraphDependencies:
    adapters: AdapterSet
    intent_router: IntentRouter
    settings: Settings
    telemetry: Telemetry


def _language(state: TutorState) -> str | None:
    for key in ("experience", "answer_submission", "recommendation_request", "report_request"):
        if (request := state.get(key)) is not None:
            return request.language
    return None


def _preferences(state: TutorState) -> AccessibilityPreferences:
    for key in ("experience", "answer_submission", "recommendation_request"):
        if (request := state.get(key)) is not None:
            return request.preferences
    return AccessibilityPreferences()


def _course_id(state: TutorState) -> str:
    if (issued := state.get("issued_question")) is not None:
        return issued.course_id
    for key in ("experience", "recommendation_request"):
        if (request := state.get(key)) is not None:
            return request.course_id
    report = state["report_request"]
    return report.course_id or report.class_id


def _option_text(item: QuizItem, option_id: str | None) -> str:
    return next((o.text for o in item.options if o.option_id == option_id), "")


def default_activity_catalog(topic: str) -> list[ActivityOption]:
    # Phase 3: replaced by the activities actually available for the course.
    return [
        ActivityOption(activity_type=a, difficulty=d, topic=topic)
        for a in ActivityType
        for d in Difficulty
    ]


class TutorNodes:
    def __init__(self, deps: GraphDependencies) -> None:
        self._deps = deps
        self._adapters = deps.adapters

    # --- entry ---------------------------------------------------------------------------------

    async def intake(self, state: TutorState) -> Update:
        workflow = state["workflow"]
        if workflow is Workflow.TEACHER_REPORT and state.get("actor_role") != "teacher":
            # Defence in depth: the application layer already enforces this.
            return {"errors": [NodeError(node="intake", code="forbidden", fatal=True)]}
        if workflow is not Workflow.EXPERIENCE:
            return {}
        request = state["experience"]
        decision = await self._deps.intent_router.decide(request.message, request.requested_format)
        return {"intent": decision, "warnings": [decision.warning] if decision.warning else []}

    def plan_experience(self, state: TutorState) -> Update:
        request = state["experience"]
        intent = state["intent"].intent
        task = INTENT_TO_TASK[intent]
        n_items = None
        if intent is Intent.NEW_EXERCISE:
            n_items = 1
        elif task in DEFAULT_ITEM_COUNT:
            n_items = state["intent"].n_items or DEFAULT_ITEM_COUNT[task]
        topic = request.topic or request.message[:200]
        # The query mirrors what the GenAI module searches for, so page checks see the same passages.
        if task in (GenerationTask.QUIZ, GenerationTask.FLASHCARDS):
            query = topic
        elif task is GenerationTask.EXPLANATION:
            query = question_for(topic, request.message)
        else:
            query = " ".join(filter(None, [request.topic, request.message]))
        plan = WorkflowPlan(
            task=task,
            topic=topic,
            retrieval_query=query[:2000],
            needs_retrieval=True,
            needs_recommendation=request.adaptive
            and (intent is Intent.NEW_EXERCISE or request.previous_activity is not None),
            n_items=n_items,
        )
        return {"plan": plan, "generation_attempts": 0}

    # --- adapter nodes -------------------------------------------------------------------------

    async def retrieve_context(self, state: TutorState) -> Update:
        plan = state["plan"]
        top_k = min(20, max(self._deps.settings.rag_top_k, plan.n_items or 0))
        try:
            response = await self._adapters.retrieval.retrieve(
                RetrievalRequest(
                    query=plan.retrieval_query,
                    course_id=_course_id(state),
                    top_k=top_k,
                    language=_language(state),
                )
            )
        except AdapterError as exc:
            return {
                "context": [],
                "retrieval_status": "unavailable",
                "warnings": ["retrieval_unavailable"],
                "errors": [NodeError(node="retrieve_context", code=exc.code, service=exc.service)],
            }
        update: Update = {
            "context": response.chunks,
            "retrieval_status": "ok" if response.chunks else "empty",
            "simulated_services": ["rag"] if response.simulated else [],
        }
        if not response.chunks:
            update["warnings"] = ["no_context_found"]
        return update

    async def generate_content(self, state: TutorState) -> Update:
        plan = state["plan"]
        attempts = state.get("generation_attempts", 0) + 1
        if plan.needs_retrieval and state.get("retrieval_status") == "empty":
            # Nothing in the course: do not let a model answer from its own knowledge.
            return {"generation": None, "generation_attempts": attempts}

        previous = state.get("verification")
        prefs = _preferences(state)
        experience = state.get("experience")
        report = state.get("report_data")
        period = state.get("report_request")
        request = GenerationRequest(
            task=plan.task,
            topic=plan.topic,
            learner_request=experience.message if experience else None,
            context=[
                ContextPassage(passage_id=c.chunk_id, page=c.source.page, text=c.text)
                for c in state.get("context", [])
            ],
            report_aggregates=report.topics if report else None,
            report_period=f"{period.period_start} → {period.period_end}" if period else None,
            preferences=GenerationPreferences(
                reading_level="simplified" if prefs.simplified_language else "standard",
                max_segment_chars=400 if prefs.short_segments else 1200,
                language=_language(state),
            ),
            n_items=plan.n_items,
            difficulty=plan.difficulty,
            remediation=state.get("remediation_input")
            if plan.task is GenerationTask.REMEDIATION
            else None,
            critic_feedback=previous.issues if previous and not previous.passed else [],
        )
        try:
            response = await self._adapters.generation.generate(request)
        except AdapterError as exc:
            return {
                "generation": None,
                "generation_attempts": attempts,
                "warnings": ["generation_unavailable"],
                "errors": [
                    NodeError(
                        node="generate_content",
                        code=exc.code,
                        service=exc.service,
                        # A failed remediation still leaves useful answer feedback.
                        fatal=state["workflow"] is not Workflow.ANSWER,
                    )
                ],
            }
        return {
            "generation": GenerationOutcome(
                content=response.content,
                prompt_version=response.prompt_version,
                model_id=response.model_id,
                pages_used=response.pages_used,
                invalid_citations=response.invalid_citations,
            ),
            "generation_attempts": attempts,
            "simulated_services": ["genai"] if response.simulated else [],
        }

    def verify_content(self, state: TutorState) -> Update:
        plan = state["plan"]
        generation = state["generation"]
        attempts = state.get("generation_attempts", 1)
        context_pages = (
            {c.source.page for c in state.get("context", []) if c.source.page}
            if state.get("retrieval_status") == "ok"
            else None
        )
        report = verify(
            plan,
            generation.content,
            context_pages=context_pages,
            invalid_citations=generation.invalid_citations
            if plan.task is GenerationTask.EXPLANATION
            else None,
        )
        self._deps.telemetry.emit(
            VERIFICATION_RESULT,
            workflow=state["workflow"].value,
            task=plan.task.value if plan.task else None,
            passed=report.passed,
            attempt=attempts,
            checks=",".join(report.checks_run),
            issues=",".join(report.issues) or None,
            notes=",".join(report.notes) or None,
        )
        update: Update = {"verification": report}
        if not report.passed and attempts >= self._deps.settings.max_generation_attempts:
            update |= {
                "generation": None,
                "warnings": ["content_verification_failed"],
                "errors": [
                    NodeError(
                        node="verify_content",
                        code="content_verification_failed",
                        fatal=state["workflow"] is not Workflow.ANSWER,
                    )
                ],
            }
        return update

    async def evaluate_answer(self, state: TutorState) -> Update:
        issued = state["issued_question"]
        item = issued.item
        submission = state["answer_submission"]
        answer = submission.answer

        def invalid(code: str) -> Update:
            return {"errors": [NodeError(node="evaluate_answer", code=code, fatal=True)]}

        if item.item_type in ("mcq", "true_false"):
            if answer.selected_option_id is None:
                return invalid("invalid_answer_format")
            correct = answer.selected_option_id == item.correct_option_id
            evaluation = AnswerEvaluation(
                question_id=item.item_id,
                is_correct=correct,
                score=1.0 if correct else 0.0,
                observed_errors=[] if correct else ["selected_incorrect_option"],
                method="answer_key",
            )
            simulated: list[str] = []
            student_text = _option_text(item, answer.selected_option_id)
            correct_text = _option_text(item, item.correct_option_id)
        else:
            if answer.text is None:
                return invalid("invalid_answer_format")
            try:
                result = await self._adapters.evaluation.evaluate(
                    AnswerEvaluationRequest(
                        question_prompt=item.prompt,
                        reference_answer=item.reference_answer,
                        student_answer=answer.text,
                        language=submission.language,
                    )
                )
            except AdapterError as exc:
                return {
                    "errors": [
                        NodeError(
                            node="evaluate_answer",
                            code="evaluation_unavailable",
                            service=exc.service,
                            fatal=True,
                        )
                    ]
                }
            evaluation = AnswerEvaluation(
                question_id=item.item_id,
                is_correct=result.is_correct,
                score=result.score,
                observed_errors=result.observed_errors,
                method="genai_evaluator",
            )
            simulated = ["genai"] if result.simulated else []
            student_text, correct_text = answer.text, item.reference_answer or ""

        wrong = not evaluation.is_correct
        update: Update = {
            "evaluation": evaluation,
            "plan": WorkflowPlan(
                task=GenerationTask.REMEDIATION if wrong else None,
                topic=issued.topic,
                # Same string the GenAI module searches for in remediate().
                retrieval_query=f"{item.prompt} {correct_text}"[:2000],
                needs_retrieval=wrong,
                needs_recommendation=submission.request_recommendation,
                n_items=1 if wrong else None,
            ),
            "generation_attempts": 0,
            "simulated_services": simulated,
        }
        if wrong:
            history = state.get("history") or HistorySnapshot()
            update["remediation_input"] = RemediationInput(
                question=item.prompt,
                student_answer=student_text or "(aucune réponse)",
                correct_answer=correct_text or item.prompt,
                history=history.error_labels[:5],
            )
        return update

    async def recommend_activity(self, state: TutorState) -> Update:
        workflow = state["workflow"]
        fatal = workflow is Workflow.LEARNING_PATH
        student_ref = state.get("student_ref")
        if not student_ref:
            return {
                "recommendation": None,
                "warnings": ["recommendation_requires_learner"],
                "errors": [
                    NodeError(node="recommend_activity", code="missing_learner", fatal=fatal)
                ],
            }

        prefs = _preferences(state)
        history = state.get("history") or HistorySnapshot()
        evaluation = state.get("evaluation")
        if workflow is Workflow.LEARNING_PATH:
            topic = state["recommendation_request"].topic
            last = None
        else:
            topic = state["plan"].topic
            previous = state["experience"].previous_activity if "experience" in state else None
            last = (
                ("correct" if evaluation.is_correct else "incorrect")
                if evaluation
                else (previous.outcome if previous else None)
            )
        scores = [*history.recent_scores, *([evaluation.score] if evaluation else [])][-10:]
        features = LearnerFeatures(
            recent_scores=scores,
            avg_time_s=history.avg_time_s,
            last_outcome=last,
            declared_needs=prefs.declared_needs(),
        )

        catalog = default_activity_catalog(topic[:200])
        try:
            response = await self._adapters.recommendation.recommend(
                RecommendationServiceRequest(
                    student_ref=student_ref,
                    course_id=_course_id(state),
                    topic=topic[:200],
                    features=features,
                    available_activities=catalog,
                )
            )
        except AdapterError as exc:
            return {
                "recommendation": None,
                "warnings": ["recommendation_unavailable"],
                "errors": [
                    NodeError(
                        node="recommend_activity", code=exc.code, service=exc.service, fatal=fatal
                    )
                ],
            }

        offered = {(o.activity_type, o.difficulty, o.topic) for o in catalog}
        if (response.activity_type, response.difficulty, response.topic) not in offered:
            return {
                "recommendation": None,
                "warnings": ["recommendation_not_available"],
                "errors": [
                    NodeError(
                        node="recommend_activity",
                        code="recommendation_not_available",
                        service="rl",
                        fatal=fatal,
                    )
                ],
            }
        return {
            "recommendation": RecommendationOutcome(
                recommendation_id=response.recommendation_id,
                activity_type=response.activity_type,
                difficulty=response.difficulty,
                topic=response.topic,
                rationale=response.rationale,
                policy_version=response.policy_version,
            ),
            "simulated_services": ["rl"] if response.simulated else [],
        }

    async def load_report_data(self, state: TutorState) -> Update:
        request = state["report_request"]
        try:
            data = await self._adapters.learning_records.summaries(
                LearningSummariesRequest(
                    class_id=request.class_id,
                    course_id=request.course_id,
                    period_start=request.period_start,
                    period_end=request.period_end,
                )
            )
        except AdapterError as exc:
            return {
                "errors": [
                    NodeError(
                        node="load_report_data", code=exc.code, service=exc.service, fatal=True
                    )
                ]
            }
        plan = WorkflowPlan(
            task=GenerationTask.REPORT_SUMMARY if data.topics else None,
            topic=request.course_id or request.class_id,
            retrieval_query="",
            needs_retrieval=False,
        )
        return {
            "report_data": data,
            "plan": plan,
            "generation_attempts": 0,
            "simulated_services": ["learning_records"] if data.simulated else [],
        }

    # --- inclusion -----------------------------------------------------------------------------

    async def attach_images(self, state: TutorState) -> Update:
        """Course figures from the retrieved pages, always with alt text; colour-adapted on request.

        Skipped when the learner declared reduced visual complexity. A missing description becomes
        an explicit placeholder, never an invented caption.
        """
        if state["workflow"] is not Workflow.EXPERIENCE or not state.get("generation"):
            return {}
        prefs = state["experience"].preferences
        if prefs.reduced_visual_complexity:
            return {}
        refs = list(dict.fromkeys(r for c in state.get("context", []) for r in c.image_refs))[
            :MAX_IMAGES
        ]
        blocks: list[ui.UIBlock] = []
        warnings: list[str] = []
        simulated: list[str] = []
        inclusion = self._adapters.inclusion
        for ref in refs:
            asset_id, adapted = ref, False
            if prefs.color_vision is not ColorVisionDeficiency.NONE:
                try:
                    result = await inclusion.adapt_colors(
                        ColorAdaptationRequest(image_ref=ref, deficiency=prefs.color_vision)
                    )
                    asset_id, adapted = result.adapted_image_ref, True
                    if result.simulated:
                        simulated.append("inclusion")
                except AdapterError:
                    warnings.append("color_adaptation_failed")
            try:
                described = await inclusion.describe_image(
                    ImageDescriptionRequest(
                        image_ref=ref,
                        language=_language(state),
                        detail="long" if prefs.screen_reader_optimized else "short",
                    )
                )
                blocks.append(
                    ui.ImageBlock(
                        asset_id=asset_id,
                        alt_text=described.alt_text,
                        long_description=described.long_description
                        if prefs.screen_reader_optimized
                        else None,
                        adapted=adapted,
                    )
                )
                if described.simulated:
                    simulated.append("inclusion")
            except AdapterError:
                warnings.append("image_description_unavailable")
                blocks.append(
                    ui.ImageBlock(
                        asset_id=asset_id, description_source="placeholder", adapted=adapted
                    )
                )
        return {"image_blocks": blocks, "warnings": warnings, "simulated_services": simulated}

    # --- presentation --------------------------------------------------------------------------

    def plan_ui(self, state: TutorState) -> Update:
        workflow = state["workflow"]
        generation = state.get("generation")
        content = generation.content if generation else None
        if content is not None:
            # Issued question ids must be unique across requests and learners.
            content = ui_planner.with_unique_item_ids(content, state["request_id"][:16])
        evidence = (
            "recurring" if state.get("evidence_count", 1) >= RECURRING_THRESHOLD else "single"
        )
        blocks: list[ui.UIBlock] = []

        if workflow is Workflow.ANSWER:
            blocks.append(
                ui_planner.feedback_block(state["evaluation"], state["issued_question"].item)
            )
        if workflow is Workflow.TEACHER_REPORT:
            blocks.extend(ui_planner.report_blocks(state["report_data"]))
            if isinstance(content, ReportSummaryContent):
                blocks.extend(ui_planner.content_blocks(content))
        elif content is not None:
            blocks.extend(ui_planner.content_blocks(content, evidence=evidence))
            # Figures follow the title: they belong to the content they illustrate.
            at = 1 if blocks and blocks[0].type == "heading" else 0
            blocks[at:at] = state.get("image_blocks", [])
        elif workflow is Workflow.EXPERIENCE and not has_fatal_error(state):
            blocks.append(ui.CalloutBlock(tone="info", message_code="no_course_content"))
        if (rec := state.get("recommendation")) is not None:
            blocks.append(ui_planner.recommendation_block(rec))

        if not blocks:
            blocks = [ui.FallbackBlock(reason_code="nothing_to_display")]
        return {"ui_blocks": blocks, "issued_questions": ui_planner.issued_items(content)}

    def recover(self, state: TutorState) -> Update:
        fatal = next((e for e in state.get("errors", []) if e.fatal), None)
        reason = "internal_error"
        if fatal is not None:
            reason = REASON_BY_NODE.get(fatal.node, fatal.code)
        return {
            "ui_blocks": [ui.FallbackBlock(reason_code=reason)],
            "fallback_used": True,
            "issued_questions": [],
        }

    def finalize(self, state: TutorState) -> Update:
        generation = state.get("generation")
        verification = state.get("verification")
        notes = verification.notes if verification else []
        warnings = list(dict.fromkeys([*state.get("warnings", []), *notes]))[:20]
        fallback_used = state.get("fallback_used", False)
        context = state.get("context", [])

        if state["workflow"] in (Workflow.EXPERIENCE, Workflow.ANSWER) and generation:
            grounding = "context_provided" if context else "no_context"
        else:
            grounding = "not_applicable"
        meta = {
            "language": _language(state),
            "grounding": grounding,
            "sources": [c.source.model_dump() for c in context][:20] if generation else [],
            "verification": verification.model_dump() if verification else None,
            "simulated": bool(state.get("simulated_services")),
            "simulated_services": sorted(set(state.get("simulated_services", []))),
            "fallback_used": fallback_used,
            "warnings": warnings,
            "prompt_version": generation.prompt_version if generation else None,
            "model_id": generation.model_id if generation else None,
        }
        blocks = state.get("ui_blocks") or [ui.FallbackBlock(reason_code="internal_error")]
        try:
            # Full re-validation from plain data: nothing unvalidated reaches the client.
            spec = ui.UISpec.model_validate(
                {"blocks": [b.model_dump(mode="json") for b in blocks], "meta": meta}
            )
        except ValidationError:
            fallback_used = True
            meta |= {"fallback_used": True, "warnings": [*warnings, "ui_validation_failed"][:20]}
            spec = ui.UISpec.model_validate(
                {
                    "blocks": [{"type": "fallback", "reason_code": "ui_validation_failed"}],
                    "meta": meta,
                }
            )

        if has_fatal_error(state) or fallback_used:
            status = ResponseStatus.FAILED
        elif state.get("warnings") or state.get("errors"):  # verification notes do not degrade
            status = ResponseStatus.DEGRADED
        else:
            status = ResponseStatus.OK
        update: Update = {"ui": spec, "status": status}
        if fallback_used:
            update["issued_questions"] = []
        return update
