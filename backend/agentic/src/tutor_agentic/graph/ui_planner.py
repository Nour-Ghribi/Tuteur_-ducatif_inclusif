"""Deterministic mapping from validated content to approved UI blocks.

The model never chooses components directly: it produces typed content, and this module decides
how that content is presented. Phase 4 adds preference-driven shaping (segment length, reduced
complexity) on top of this baseline mapping.
"""

from __future__ import annotations

from ..integrations.contracts import LearningSummariesResponse
from ..schemas import ui
from ..schemas.content import (
    ComparisonContent,
    ConceptCardsContent,
    ConceptMapContent,
    EducationalContent,
    ExplanationContent,
    FlashcardsContent,
    QuizContent,
    QuizItem,
    RemediationContent,
    ReportSummaryContent,
    StepsContent,
)
from ..state import AnswerEvaluation, RecommendationOutcome


def quiz_block(quiz: QuizContent) -> ui.QuizBlock:
    """Learner-facing view: answer keys, references and explanations are stripped."""
    return ui.QuizBlock(
        title=quiz.title,
        questions=[
            ui.QuizQuestionView(
                question_id=item.item_id,
                item_type=item.item_type,
                prompt=item.prompt,
                options=[
                    ui.QuizOptionView(option_id=o.option_id, text=o.text) for o in item.options
                ],
            )
            for item in quiz.items
        ],
    )


def explanation_blocks(content: ExplanationContent) -> list[ui.UIBlock]:
    blocks: list[ui.UIBlock] = [ui.HeadingBlock(text=content.title, level=2)]
    for section in content.sections:
        if section.heading:
            blocks.append(ui.HeadingBlock(text=section.heading, level=3))
        blocks.append(ui.TextBlock(text=section.body))
    if content.key_points:
        blocks.append(ui.HeadingBlock(text_code="key_points", level=3))
        blocks.append(ui.BulletListBlock(items=content.key_points))
    return blocks


def content_blocks(content: EducationalContent, evidence: str = "single") -> list[ui.UIBlock]:
    if isinstance(content, ExplanationContent):
        return explanation_blocks(content)
    if isinstance(content, QuizContent):
        return [quiz_block(content)]
    if isinstance(content, FlashcardsContent):
        return [
            ui.FlashcardDeckBlock(
                title=content.title,
                cards=[ui.FlashcardView(front=c.front, back=c.back) for c in content.cards],
            )
        ]
    if isinstance(content, ConceptCardsContent):
        return [
            ui.ConceptCardsBlock(
                title=content.title,
                concepts=[
                    ui.ConceptView(term=c.term, definition=c.definition, example=c.example)
                    for c in content.concepts
                ],
            )
        ]
    if isinstance(content, ConceptMapContent):
        return [
            ui.ConceptMapBlock(
                title=content.title,
                central_node_id=content.central_node_id,
                nodes=[ui.MapNodeView(node_id=n.node_id, label=n.label) for n in content.nodes],
                edges=[
                    ui.MapEdgeView(source=e.source, target=e.target, label=e.label)
                    for e in content.edges
                ],
            )
        ]
    if isinstance(content, StepsContent):
        return [
            ui.StepsBlock(
                title=content.title,
                steps=[ui.StepView(title=s.title, detail=s.detail) for s in content.steps],
            )
        ]
    if isinstance(content, ComparisonContent):
        return [
            ui.ComparisonTableBlock(
                title=content.title,
                columns=content.items,
                rows=[
                    ui.ComparisonRowView(criterion=r.criterion, values=r.values)
                    for r in content.rows
                ],
            )
        ]
    if isinstance(content, RemediationContent):
        blocks: list[ui.UIBlock] = [ui.CalloutBlock(tone="info", message_code="remediation_intro")]
        if content.diagnostic:
            # An inferred confusion, never an observed fact: the wording depends on the evidence.
            code = (
                "misconception_hypothesis_recurring"
                if evidence == "recurring"
                else "misconception_hypothesis"
            )
            blocks.append(ui.CalloutBlock(tone="info", message_code=code, text=content.diagnostic))
        blocks += [ui.TextBlock(text=content.explanation), quiz_block(content.exercise)]
        return blocks
    if isinstance(content, ReportSummaryContent):
        blocks: list[ui.UIBlock] = [ui.TextBlock(text=content.summary)]
        if content.recurring_difficulties:
            blocks.append(ui.HeadingBlock(text_code="recurring_difficulties", level=3))
            blocks.append(ui.BulletListBlock(items=content.recurring_difficulties))
        return blocks
    return [ui.FallbackBlock(reason_code="unsupported_content")]


def _rekey(quiz: QuizContent, prefix: str) -> QuizContent:
    items = [i.model_copy(update={"item_id": f"{prefix}-{i.item_id}"[:64]}) for i in quiz.items]
    return quiz.model_copy(update={"items": items})


def with_unique_item_ids(content: EducationalContent, prefix: str) -> EducationalContent:
    if isinstance(content, QuizContent):
        return _rekey(content, prefix)
    if isinstance(content, RemediationContent):
        return content.model_copy(update={"exercise": _rekey(content.exercise, prefix)})
    return content


def issued_items(content: EducationalContent | None) -> list[QuizItem]:
    if isinstance(content, QuizContent):
        return list(content.items)
    if isinstance(content, RemediationContent):
        return list(content.exercise.items)
    return []


def feedback_block(evaluation: AnswerEvaluation, item: QuizItem) -> ui.QuizFeedbackBlock:
    return ui.QuizFeedbackBlock(
        question_id=evaluation.question_id,
        is_correct=evaluation.is_correct,
        score=evaluation.score,
        correct_option_id=item.correct_option_id,
        explanation=item.explanation,
        observed_errors=evaluation.observed_errors,
    )


def recommendation_block(rec: RecommendationOutcome) -> ui.RecommendationCardBlock:
    return ui.RecommendationCardBlock(
        recommendation_id=rec.recommendation_id,
        activity_type=rec.activity_type,
        difficulty=rec.difficulty,
        topic=rec.topic,
        rationale=rec.rationale,
        source="policy",
    )


def report_blocks(data: LearningSummariesResponse) -> list[ui.UIBlock]:
    attempts = sum(t.attempts for t in data.topics)
    success = sum(t.success_rate * t.attempts for t in data.topics) / attempts if attempts else 0.0
    blocks: list[ui.UIBlock] = [
        ui.MetricGridBlock(
            metrics=[
                ui.Metric(label_code="learner_count", value=data.learner_count, unit="count"),
                ui.Metric(label_code="attempts", value=attempts, unit="count"),
                ui.Metric(label_code="success_rate", value=round(success, 3), unit="ratio"),
            ]
        )
    ]
    if data.topics:
        blocks.append(
            ui.BarChartBlock(
                title_code="success_rate_by_topic",
                value_unit="ratio",
                bars=[ui.Bar(label=t.topic, value=t.success_rate) for t in data.topics[:30]],
            )
        )
    else:
        blocks.append(ui.CalloutBlock(tone="info", message_code="no_data_for_period"))
    return blocks


def progress_blocks(snapshot) -> list[ui.UIBlock]:
    """Learner progress from the server-side history (no history -> an explicit empty state)."""
    if not snapshot.attempts_total:
        return [ui.CalloutBlock(tone="info", message_code="no_progress_yet")]
    scores = snapshot.recent_scores
    blocks: list[ui.UIBlock] = [
        ui.MetricGridBlock(
            metrics=[ui.Metric(label_code="attempts", value=snapshot.attempts_total, unit="count")]
        ),
    ]
    if scores:
        blocks.append(
            ui.ProgressBlock(label_code="recent_success", value=round(sum(scores) / len(scores), 3))
        )
    return blocks
