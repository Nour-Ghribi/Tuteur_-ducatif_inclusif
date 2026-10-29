"""Conditional-edge functions. Pure functions of the state, so routing is unit-testable."""

from __future__ import annotations

from ..schemas.common import Workflow
from ..state import TutorState, has_fatal_error

ENTRY_BY_WORKFLOW = {
    Workflow.EXPERIENCE: "plan_experience",
    Workflow.ANSWER: "evaluate_answer",
    Workflow.LEARNING_PATH: "recommend_activity",
    Workflow.TEACHER_REPORT: "load_report_data",
}


def after_intake(state: TutorState) -> str:
    if has_fatal_error(state):
        return "recover"
    return ENTRY_BY_WORKFLOW[state["workflow"]]


def after_plan(state: TutorState) -> str:
    return "retrieve_context" if state["plan"].needs_retrieval else "generate_content"


def after_content(state: TutorState) -> str:
    """Next step once content exists, or once content generation was abandoned (non-fatal)."""
    if has_fatal_error(state):
        return "recover"
    plan = state.get("plan")
    return "recommend_activity" if plan and plan.needs_recommendation else "attach_images"


def after_evaluation(state: TutorState) -> str:
    if has_fatal_error(state):
        return "recover"
    if state["plan"].task is not None:
        return "retrieve_context"
    return after_content(state)


def after_report_data(state: TutorState) -> str:
    if has_fatal_error(state):
        return "recover"
    return "generate_content" if state["plan"].task is not None else "attach_images"


def after_generation(state: TutorState) -> str:
    if state.get("generation") is None:
        return after_content(state)
    return "verify_content"


def after_verification(state: TutorState) -> str:
    # verify_content drops the content once attempts are exhausted, which bounds this loop.
    if state.get("generation") is None or state["verification"].passed:
        return after_content(state)
    return "generate_content"


def after_recommendation(state: TutorState) -> str:
    return "recover" if has_fatal_error(state) else "attach_images"
