from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from app.rag.llm_client import generate_chat_completion, llm_is_configured
from app.rag.tool_runner import ToolCall, ToolObservation


AgentAction = Literal["call_tool", "final_answer", "ask_clarification"]


@dataclass
class AgentStep:
    action: AgentAction
    reason: str
    source: str = "agent_policy"
    tool_call: Optional[ToolCall] = None
    observation_summary: Dict[str, Any] = field(default_factory=dict)

    def to_trace(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "source": self.source,
            "reason": self.reason,
            "tool_name": self.tool_call.name if self.tool_call else None,
            "call_id": self.tool_call.call_id if self.tool_call else None,
            "observation": self.observation_summary,
        }


class AgentLoopController:
    """Choose the agent's next step from tool observations and allowed candidates."""

    def decide_next(
        self,
        *,
        user_query: str,
        plan: Any,
        observations: List[ToolObservation],
        candidate_calls: List[ToolCall],
    ) -> AgentStep:
        last_observation = observations[-1] if observations else None
        if last_observation and not last_observation.insufficient:
            return AgentStep(
                action="final_answer",
                reason="latest_tool_observation_is_sufficient",
                source="agent_policy",
                observation_summary=self._summarize_observation(last_observation),
            )
        if last_observation and self._is_hard_refusal(last_observation):
            return AgentStep(
                action="final_answer",
                reason="latest_tool_observation_is_boundary_refusal",
                source="agent_policy",
                observation_summary=self._summarize_observation(last_observation),
            )

        llm_step = self._decide_with_llm(
            user_query=user_query,
            plan=plan,
            observations=observations,
            candidate_calls=candidate_calls,
        )
        if llm_step:
            return llm_step

        if candidate_calls:
            return AgentStep(
                action="call_tool",
                reason="fallback_selected_next_candidate_tool",
                source="agent_policy_fallback",
                tool_call=candidate_calls[0],
                observation_summary=self._summarize_observation(last_observation),
            )

        return AgentStep(
            action="ask_clarification",
            reason="no_more_candidate_tools_after_insufficient_observation",
            source="agent_policy_fallback",
            observation_summary=self._summarize_observation(last_observation),
        )

    def _decide_with_llm(
        self,
        *,
        user_query: str,
        plan: Any,
        observations: List[ToolObservation],
        candidate_calls: List[ToolCall],
    ) -> Optional[AgentStep]:
        if not llm_is_configured() or not observations:
            return None
        candidate_names = [call.name for call in candidate_calls]
        observation_payload = [self._summarize_observation(item) for item in observations[-3:]]
        system_prompt = (
            "You are the control loop for a scenic-guide agent. "
            "Choose the next action from tool observations. Return strict JSON only."
        )
        prompt = (
            f"User query: {user_query}\n"
            f"Planner first action: {getattr(plan, 'strategy', '')}, "
            f"question_type: {getattr(plan, 'question_type', '')}\n"
            f"Recent observations: {json.dumps(observation_payload, ensure_ascii=False)}\n"
            f"Allowed next tools: {json.dumps(candidate_names, ensure_ascii=False)}\n"
            "Return JSON: "
            '{"action":"call_tool|final_answer|ask_clarification","tool_name":"one allowed tool or empty",'
            '"reason":"brief reason"}\n'
            "Use final_answer if evidence is enough or the observation is a boundary refusal. "
            "Use call_tool only if one allowed tool is likely to repair an insufficient observation. "
            "Use ask_clarification if tools cannot safely answer without a missing slot."
        )
        try:
            raw = generate_chat_completion(
                prompt,
                system_prompt=system_prompt,
                temperature=0.0,
                max_tokens=180,
                return_error_text=False,
            )
            payload = self._parse_json(raw)
        except Exception:
            return None
        if not payload:
            return None

        action = str(payload.get("action") or "").strip()
        reason = str(payload.get("reason") or "llm_selected_next_agent_step").strip()
        if action == "final_answer":
            return AgentStep(
                action="final_answer",
                reason=reason,
                source="agent_llm",
                observation_summary=self._summarize_observation(observations[-1]),
            )
        if action == "ask_clarification":
            return AgentStep(
                action="ask_clarification",
                reason=reason,
                source="agent_llm",
                observation_summary=self._summarize_observation(observations[-1]),
            )
        if action == "call_tool":
            tool_name = str(payload.get("tool_name") or "").strip()
            for call in candidate_calls:
                if call.name == tool_name:
                    call.reason = reason or call.reason
                    return AgentStep(
                        action="call_tool",
                        reason=reason,
                        source="agent_llm",
                        tool_call=call,
                        observation_summary=self._summarize_observation(observations[-1]),
                    )
        return None

    @staticmethod
    def _is_hard_refusal(observation: ToolObservation) -> bool:
        reason = str((observation.refusal or {}).get("reason") or "")
        return reason in {"source_conflict", "realtime_required", "unsupported_fact_request"}

    @staticmethod
    def _summarize_observation(observation: Optional[ToolObservation]) -> Dict[str, Any]:
        if not observation:
            return {}
        return {
            "tool_name": observation.tool_name,
            "ok": observation.ok,
            "status": observation.status,
            "response_kind": observation.response_kind,
            "evidence_count": len(observation.evidence or []),
            "refusal_reason": (observation.refusal or {}).get("reason"),
            "warnings": list(observation.warnings or [])[:5],
            "missing_slots": list(observation.missing_slots or [])[:5],
            "suggested_next_tools": list(observation.suggested_next_tools or [])[:5],
            "insufficient": observation.insufficient,
            "error": observation.error,
        }

    @staticmethod
    def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
        text = str(raw or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return payload if isinstance(payload, dict) else None
