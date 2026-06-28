from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import END, StateGraph

from app.rag.graph_nodes import (
    NodeContext,
    make_agent_loop_decide_node,
    make_fast_answer_node,
    make_finalize_node,
    make_plan_node,
    make_repair_execute_node,
    make_review_node,
    make_synthesize_node,
    make_tool_dispatch_node,
    make_tool_execute_node,
    route_after_agent_loop_decide,
    route_after_plan,
    route_after_repair,
    route_after_review,
    route_after_tool_dispatch,
)
from app.rag.graph_state import GraphState


def build_graph(ctx: NodeContext | None = None) -> Any:
    if ctx is None:
        ctx = NodeContext()

    g = StateGraph(GraphState)

    g.add_node("planner", make_plan_node(ctx))
    g.add_node("fast_answer", make_fast_answer_node(ctx))
    g.add_node("tool_dispatch", make_tool_dispatch_node(ctx))
    g.add_node("tool_execute", make_tool_execute_node(ctx))
    g.add_node("agent_loop_decide", make_agent_loop_decide_node(ctx))
    g.add_node("synthesize", make_synthesize_node(ctx))
    g.add_node("review", make_review_node(ctx))
    g.add_node("repair_execute", make_repair_execute_node(ctx))
    g.add_node("finalize", make_finalize_node(ctx))

    g.set_entry_point("planner")

    g.add_conditional_edges("planner", route_after_plan, {
        "fast_answer": "fast_answer",
        "tool_dispatch": "tool_dispatch",
        "finalize": "finalize",
    })

    g.add_edge("fast_answer", "finalize")
    g.add_conditional_edges("tool_dispatch", route_after_tool_dispatch, {
        "tool_execute": "tool_execute",
    })
    g.add_edge("tool_execute", "agent_loop_decide")

    g.add_conditional_edges("agent_loop_decide", route_after_agent_loop_decide, {
        "tool_execute": "tool_execute",
        "synthesize": "synthesize",
    })

    g.add_edge("synthesize", "review")

    g.add_conditional_edges("review", route_after_review, {
        "finalize": "finalize",
        "repair_execute": "repair_execute",
    })

    g.add_conditional_edges("repair_execute", route_after_repair, {
        "synthesize": "synthesize",
    })

    g.add_edge("finalize", END)

    return g.compile()


@lru_cache(maxsize=1)
def get_graph() -> Any:
    return build_graph()
