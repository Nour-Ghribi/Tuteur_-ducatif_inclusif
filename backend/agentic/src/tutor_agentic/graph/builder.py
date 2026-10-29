"""Assembles the tutor graph.

intake ─┬─ experience ─► plan_experience ─► [retrieve_context] ─► generate_content
        │                                                       ▲        │
        │                                     (critic feedback) └─ verify_content
        ├─ answer ─────► evaluate_answer ─► (wrong) retrieve ─► generate (remediation) …
        ├─ learning ───► recommend_activity
        └─ report ─────► load_report_data ─► generate_content (summary) …
… ─► [recommend_activity] ─► plan_ui ─► finalize        any fatal error ─► recover ─► finalize
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..state import TutorState
from . import edges
from .nodes import GraphDependencies, TutorNodes


def build_tutor_graph(deps: GraphDependencies):
    nodes = TutorNodes(deps)
    graph = StateGraph(TutorState)

    graph.add_node("intake", nodes.intake)
    graph.add_node("plan_experience", nodes.plan_experience)
    graph.add_node("retrieve_context", nodes.retrieve_context)
    graph.add_node("generate_content", nodes.generate_content)
    graph.add_node("verify_content", nodes.verify_content)
    graph.add_node("evaluate_answer", nodes.evaluate_answer)
    graph.add_node("recommend_activity", nodes.recommend_activity)
    graph.add_node("load_report_data", nodes.load_report_data)
    graph.add_node("attach_images", nodes.attach_images)
    graph.add_node("plan_ui", nodes.plan_ui)
    graph.add_node("recover", nodes.recover)
    graph.add_node("finalize", nodes.finalize)

    graph.add_edge(START, "intake")
    graph.add_conditional_edges(
        "intake",
        edges.after_intake,
        ["plan_experience", "evaluate_answer", "recommend_activity", "load_report_data", "recover"],
    )
    graph.add_conditional_edges(
        "plan_experience", edges.after_plan, ["retrieve_context", "generate_content"]
    )
    graph.add_edge("retrieve_context", "generate_content")
    graph.add_conditional_edges(
        "generate_content",
        edges.after_generation,
        ["verify_content", "recommend_activity", "attach_images", "recover"],
    )
    graph.add_conditional_edges(
        "verify_content",
        edges.after_verification,
        ["generate_content", "recommend_activity", "attach_images", "recover"],
    )
    graph.add_conditional_edges(
        "evaluate_answer",
        edges.after_evaluation,
        ["retrieve_context", "recommend_activity", "attach_images", "recover"],
    )
    graph.add_conditional_edges(
        "load_report_data",
        edges.after_report_data,
        ["generate_content", "attach_images", "recover"],
    )
    graph.add_conditional_edges(
        "recommend_activity", edges.after_recommendation, ["attach_images", "recover"]
    )
    graph.add_edge("attach_images", "plan_ui")
    graph.add_edge("plan_ui", "finalize")
    graph.add_edge("recover", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(name="tutor_graph")
