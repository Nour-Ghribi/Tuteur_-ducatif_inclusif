from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from tutor_agentic.integrations.contracts import ColorAdaptationRequest, GenerationResponse
from tutor_agentic.schemas import UISpec
from tutor_agentic.schemas.common import AccessibilityPreferences, ColorVisionDeficiency
from tutor_agentic.schemas.content import ConceptMapContent, QuizContent, QuizItem
from tutor_agentic.schemas.requests import ExperienceRequest, StudentAnswer, TeacherReportRequest
from tutor_agentic.schemas.ui import ALLOWED_BLOCK_TYPES, HeadingBlock, UIBlock

MCQ = {
    "item_id": "q1",
    "item_type": "mcq",
    "prompt": "?",
    "options": [{"option_id": "a", "text": "A"}, {"option_id": "b", "text": "B"}],
    "correct_option_id": "a",
}


class TestContent:
    def test_valid_mcq(self):
        assert QuizItem.model_validate(MCQ).correct_option_id == "a"

    @pytest.mark.parametrize(
        "patch",
        [
            {"correct_option_id": "z"},  # answer key not among options
            {"options": [{"option_id": "a", "text": "A"}]},  # too few options
            {"options": [{"option_id": "a", "text": "A"}, {"option_id": "a", "text": "B"}]},
            {"item_type": "short_answer"},  # short answer needs a reference and no options
            {"prompt": ""},
            {"item_type": "essay"},
        ],
    )
    def test_malformed_items_are_rejected(self, patch):
        with pytest.raises(ValidationError):
            QuizItem.model_validate(MCQ | patch)

    def test_duplicate_item_ids_rejected(self):
        with pytest.raises(ValidationError):
            QuizContent.model_validate({"title": "t", "items": [MCQ, MCQ]})

    def test_concept_map_edges_must_reference_nodes(self):
        with pytest.raises(ValidationError):
            ConceptMapContent.model_validate(
                {
                    "title": "t",
                    "central_node_id": "a",
                    "nodes": [{"node_id": "a", "label": "A"}, {"node_id": "b", "label": "B"}],
                    "edges": [{"source": "a", "target": "ghost"}],
                }
            )

    @pytest.mark.parametrize(
        "payload",
        [
            {"content": {"kind": "html", "markup": "<script>alert(1)</script>"}},
            {"content": "<div>raw html</div>"},
            {"content": {"kind": "quiz", "title": "t", "items": []}},
            {},
        ],
    )
    def test_malformed_llm_output_is_rejected(self, payload):
        with pytest.raises(ValidationError):
            GenerationResponse.model_validate(payload)

    def test_additive_fields_from_services_are_tolerated(self):
        response = GenerationResponse.model_validate(
            {"content": {"kind": "quiz", "title": "t", "items": [MCQ]}, "new_field": 1}
        )
        assert response.simulated is False


class TestUISpec:
    def test_unknown_block_type_rejected(self):
        with pytest.raises(ValidationError):
            UISpec.model_validate({"blocks": [{"type": "iframe", "src": "https://x"}]})

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            UISpec.model_validate({"blocks": [{"type": "text", "text": "a", "html": "<b>"}]})

    def test_empty_and_oversized_specs_rejected(self):
        with pytest.raises(ValidationError):
            UISpec.model_validate({"blocks": []})
        with pytest.raises(ValidationError):
            UISpec.model_validate({"blocks": [{"type": "text", "text": "x"}] * 41})

    def test_heading_needs_exactly_one_label(self):
        with pytest.raises(ValidationError):
            HeadingBlock()
        with pytest.raises(ValidationError):
            HeadingBlock(text="a", text_code="b")

    def test_allowed_types_match_union(self):
        union_types = {
            m.model_fields["type"].default
            for m in UIBlock.__origin__.__args__  # type: ignore[attr-defined]
        }
        assert union_types == ALLOWED_BLOCK_TYPES


class TestRequests:
    def test_student_answer_requires_exactly_one_form(self):
        with pytest.raises(ValidationError):
            StudentAnswer()
        with pytest.raises(ValidationError):
            StudentAnswer(selected_option_id="a", text="b")

    def test_unknown_fields_rejected(self):
        with pytest.raises(ValidationError):
            ExperienceRequest(message="x", course_id="c", student_ref="spoofed")

    def test_report_period_validation(self):
        today = date.today()
        with pytest.raises(ValidationError):
            TeacherReportRequest(class_id="c", period_start=today, period_end=today - timedelta(1))
        with pytest.raises(ValidationError):
            TeacherReportRequest(class_id="c", period_start=today, period_end=today + timedelta(1))
        with pytest.raises(ValidationError):
            TeacherReportRequest(
                class_id="c", period_start=today - timedelta(400), period_end=today
            )

    def test_declared_needs_only_reflect_explicit_preferences(self):
        assert AccessibilityPreferences().declared_needs() == []
        prefs = AccessibilityPreferences(
            short_segments=True, color_vision=ColorVisionDeficiency.DEUTERANOPIA
        )
        assert prefs.declared_needs() == ["short_segments", "color_vision:deuteranopia"]

    def test_color_adaptation_needs_declared_deficiency(self):
        with pytest.raises(ValidationError):
            ColorAdaptationRequest(image_ref="img-1", deficiency=ColorVisionDeficiency.NONE)
