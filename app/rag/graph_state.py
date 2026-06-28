from __future__ import annotations

import operator
from typing import Any, Dict, List, Optional

from typing_extensions import Annotated, TypedDict


def _add_int(a: int, b: int) -> int:
    """Reducer for tool_loop_count: sum contributions from parallel nodes."""
    return (a or 0) + (b or 0)


class GraphState(TypedDict, total=False):
    # --- inputs ---
    user_query: str
    conversation_context: List[Dict[str, Any]]
    session_memory: Dict[str, Any]
    user_profile: Optional[str]
    scenic_slug: Optional[str]
    attraction_id: Optional[str]
    start_attraction: Optional[str]
    forced_recommendation_profile: Optional[str]
    forced_recommendation_title: Optional[str]

    # --- fast-path ---
    fast_path_result: Optional[Dict[str, Any]]

    # --- planning ---
    plan: Optional[Any]           # QueryPlan dataclass
    context_attraction: Optional[str]

    # --- tool loop ---
    # Annotated with operator.add so parallel tool_execute nodes can each append
    # their single result without conflicting writes.
    tool_observations: Annotated[List[Any], operator.add]   # List[ToolObservation]
    agent_steps: Annotated[List[Any], operator.add]         # List[AgentStep]
    seen_tools: Annotated[List[str], operator.add]
    tool_loop_count: Annotated[int, _add_int]
    # candidate_tool_calls is replaced wholesale each step — no reducer needed.
    candidate_tool_calls: List[Any]  # List[ToolCall]

    # --- review / repair ---
    review_result: Optional[Dict[str, Any]]
    repair_count: int
    repair_history: List[Dict[str, Any]]

    # --- synthesized result (pre-finalize) ---
    result: Optional[Dict[str, Any]]
    trace: Dict[str, Any]

    # --- final output fields (mirrors _finalize_response payload) ---
    final_answer: str
    response_kind: str
    evidence: List[Dict[str, Any]]
    refusal: Optional[Dict[str, Any]]
    warnings: List[str]
    recommendation: Optional[Dict[str, Any]]
    matched_attraction: Optional[str]
    recommendation_label: Optional[str]
    intent: str
    agent_type: str

    # --- post-finalize metadata (written by finalize_node) ---
    finalized_plan: Dict[str, Any]
    latency_ms: float

    # --- tts ---
    tts_style: str  # Edge-TTS mstts:express-as style, e.g. "gentle"

    # --- timing ---
    latency_start: float
