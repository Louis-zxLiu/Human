from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from app.core.runtime import utc_timestamp
from app.rag.graph import build_graph
from app.rag.graph_nodes import (
    NodeContext,
    _plan_payload,
)
from app.rag.graph_state import GraphState
from app.rag.llm_client import generate_chat_completion

# Human-readable labels for each LangGraph node, used for frontend progress display.



AGENT_NODE_LABELS: Dict[str, str] = {
    "planner": "意图解析",
    "fast_answer": "快速回答",
    "tool_dispatch": "工具调度",
    "tool_execute": "工具执行",
    "agent_loop_decide": "循环判断",
    "synthesize": "综合生成",
    "review": "质量审核",
    "repair_execute": "修复执行",
    "finalize": "最终输出",
}


class ScenicRAGPipeline:
    """Unified runtime pipeline for FACT / ANALYTICS / RECOMMEND.

    Internally driven by a LangGraph StateGraph; the public API is unchanged.
    """

    # Attributes that proxy through to NodeContext so tests can swap them
    _CTX_ATTRS = frozenset({
        "fact_agent", "analytics_agent", "recommendation_agent",
        "planner", "tool_runner", "agent_loop", "answer_review_agent",
    })

    def __init__(self) -> None:
        self._ctx = NodeContext()
        # point ctx.llm_fn at this module's generate_chat_completion so tests
        # can patch app.rag.pipeline.generate_chat_completion and have it take effect
        import app.rag.pipeline as _self_module
        self._ctx.llm_fn = lambda *a, **kw: _self_module.generate_chat_completion(*a, **kw)
        self._graph = build_graph(self._ctx)

    def __getattr__(self, name: str):
        if name in ScenicRAGPipeline._CTX_ATTRS:
            return getattr(self._ctx, name)
        raise AttributeError(f"'ScenicRAGPipeline' object has no attribute {name!r}")

    def __setattr__(self, name: str, value) -> None:
        if name in ScenicRAGPipeline._CTX_ATTRS:
            setattr(self._ctx, name, value)
        else:
            super().__setattr__(name, value)

    def process_query(
        self,
        user_query: str,
        user_profile: Optional[str] = None,
        start_attraction: Optional[str] = None,
        scenic_slug: Optional[str] = None,
        attraction_id: Optional[str] = None,
        forced_recommendation_profile: Optional[str] = None,
        forced_recommendation_title: Optional[str] = None,
        conversation_context: Optional[List[Dict[str, Any]]] = None,
        session_memory: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        initial: GraphState = {
            "user_query": user_query,
            "conversation_context": conversation_context or [],
            "session_memory": session_memory or {},
            "user_profile": user_profile,
            "scenic_slug": scenic_slug,
            "attraction_id": attraction_id,
            "start_attraction": start_attraction,
            "forced_recommendation_profile": forced_recommendation_profile,
            "forced_recommendation_title": forced_recommendation_title,
            "latency_start": time.perf_counter(),
            # mutable lists / counters must be initialised here
            "tool_observations": [],
            "agent_steps": [],
            "candidate_tool_calls": [],
            "seen_tools": [],
            "tool_loop_count": 0,
            "repair_count": 0,
            "repair_history": [],
            "trace": {},
        }

        final: GraphState = self._graph.invoke(initial)
        return self._state_to_response(user_query, final)

    async def async_stream_events(
        self,
        user_text: str,
        gps_status: str = "normal",
        session_key: str = "",
        user_profile: Optional[str] = None,
        scenic_slug: Optional[str] = None,
        attraction_id: Optional[str] = None,
        conversation_context: Optional[List[Dict[str, Any]]] = None,
        session_memory: Optional[Dict[str, Any]] = None,
        forced_recommendation_profile: Optional[str] = None,
        forced_recommendation_title: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream per-node progress events using LangGraph astream(), then yield a final ``__final__`` event.

        Each intermediate event has the shape::

            {"node": "<name>", "status": "done", "ts": <float>}

        The terminal event has the shape::

            {"node": "__final__", "status": "done", "ts": <float>, "data": <response dict>}
        """
        initial: GraphState = {
            "user_query": user_text,
            "conversation_context": conversation_context or [],
            "session_memory": session_memory or {},
            "user_profile": user_profile,
            "scenic_slug": scenic_slug,
            "attraction_id": attraction_id,
            "start_attraction": None,
            "forced_recommendation_profile": forced_recommendation_profile,
            "forced_recommendation_title": forced_recommendation_title,
            "latency_start": time.perf_counter(),
            "tool_observations": [],
            "agent_steps": [],
            "candidate_tool_calls": [],
            "seen_tools": [],
            "tool_loop_count": 0,
            "repair_count": 0,
            "repair_history": [],
            "trace": {},
        }

        # Use LangGraph's native astream() so each node event is yielded progressively
        # (not buffered), giving the client real-time progress updates.
        merged_state: GraphState = {}  # type: ignore[assignment]
        async for chunk in self._graph.astream(initial, stream_mode="updates"):
            # chunk is a dict: {node_name: updated_state_slice}
            for node_name, state_slice in chunk.items():
                if isinstance(state_slice, dict):
                    merged_state.update(state_slice)
                yield {"node": node_name, "status": "done", "ts": time.time()}

        # Merge initial state with accumulated updates for _state_to_response
        full_state: GraphState = {**initial, **merged_state}  # type: ignore[misc]
        response = self._state_to_response(user_text, full_state)
        yield {"node": "__final__", "status": "done", "ts": time.time(), "data": response}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _state_to_response(user_query: str, state: GraphState) -> Dict[str, Any]:
        plan_data = state.get("finalized_plan") or {}
        latency_ms = state.get("latency_ms", 0.0)
        trace: dict = dict(state.get("trace") or {})
        evidence = state.get("evidence") or []
        refusal = state.get("refusal")
        warnings: list = list(state.get("warnings") or [])

        payload = {
            "query": user_query,
            "intent": state.get("intent", "CHAT"),
            "agent_type": state.get("agent_type", "dialog_agent"),
            "answer": state.get("final_answer", ""),
            "matched_attraction": state.get("matched_attraction"),
            "recommendation_label": state.get("recommendation_label"),
            "response_kind": state.get("response_kind", "fact"),
            "recommendation": state.get("recommendation"),
            "plan": plan_data,
            "evidence": evidence,
            "refusal": refusal,
            "warnings": warnings,
            "tts_style": state.get("tts_style", "gentle"),
            "observability": {
                "timestamp": utc_timestamp(),
                "latency_ms": latency_ms,
                "evidence_count": len(evidence),
                "fallback_used": bool(trace.get("fallback_used")),
                "refusal_reason": (refusal or {}).get("reason"),
                "strategy": plan_data.get("strategy"),
                "trace": trace,
            },
        }
        return payload


# ---------------------------------------------------------------------------
# Module-level singleton (used by app/api/chat.py via get_pipeline())
# ---------------------------------------------------------------------------

_pipeline_instance: Optional[ScenicRAGPipeline] = None


def get_pipeline() -> ScenicRAGPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = ScenicRAGPipeline()
    return _pipeline_instance
