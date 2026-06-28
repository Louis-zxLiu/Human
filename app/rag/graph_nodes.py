from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Union

from langgraph.types import Send

from app.rag.agent_loop import AgentLoopController, AgentStep
from app.rag.answer_review_agent import AnswerReviewAgent
from app.rag.fact_agent import ScenicFactAgent, extract_interest_label
from app.rag.graph_state import GraphState
from app.rag.planner import QueryPlanner
from app.rag.recommendation_agent import ScenicRecommendationAgent
from app.rag.response_contract import make_refusal
from app.rag.sql_agent import TouristAnalyticsAgent
from app.rag.tool_runner import ToolCall, ToolObservation, ToolRunner


# ---------------------------------------------------------------------------
# Shared helpers (replicated from pipeline.py to avoid circular imports)
# ---------------------------------------------------------------------------

import json
import re

REFERENCE_PRONOUN_PATTERN = re.compile(r"(它|这里|这个景点|这个地方|刚才那个|刚刚那个|上一个|这个)")



def _build_clarification_reply(user_query: str, question_type: Optional[str] = None, scenic_slug: Optional[str] = None) -> str:
    query = str(user_query or "")
    if question_type == "highlights":
        return "可以，我先帮你缩小范围。你想了解哪个景点的看点？也可以告诉我你偏自然风光、历史文化、亲子还是拍照打卡。"
    if question_type in ("route", "route_planner"):
        return "可以规划。你从哪个位置出发，同行有没有老人或孩子，想轻松逛还是多看几个核心景点？"
    if scenic_slug:
        return "可以介绍。你想了解哪个具体景点？如果还没确定，我可以先从代表性景点、历史文化、主要看点或游览建议里选一个方向讲。"
    return "可以介绍。你想了解哪个城市、景区或具体景点？如果还没确定，也可以告诉我偏自然风光、历史文化、亲子游还是拍照打卡。"




def _agent_type_for_tool(tool_name: str) -> str:
    return {
        "behavior_sql": "behavior_analytics",
        "route_planner": "scenic_recommendation",
        "structured_fact": "scenic_fact",
        "hybrid_rag": "scenic_fact",
    }.get(tool_name, "dialog_agent")


def _plan_payload(plan: Any) -> Dict[str, Any]:
    return {
        "strategy": plan.strategy,
        "question_type": plan.question_type,
        "route_profile": plan.route_profile,
        "confidence": plan.confidence,
        "reasoning": plan.reasoning,
        "scenic_slug": plan.scenic_slug,
        "planner_source": getattr(plan, "planner_source", ""),
        "raw_payload": getattr(plan, "raw_payload", {}),
    }


# ---------------------------------------------------------------------------
# NodeContext — holds all agent singletons, injected into node factories
# ---------------------------------------------------------------------------

class NodeContext:
    def __init__(self) -> None:
        self.fact_agent = ScenicFactAgent()
        self.analytics_agent = TouristAnalyticsAgent()
        self.planner = QueryPlanner()
        self.recommendation_agent = ScenicRecommendationAgent(
            fact_agent=self.fact_agent,
            analytics_agent=self.analytics_agent,
        )
        self.tool_runner = ToolRunner(
            fact_agent=self.fact_agent,
            analytics_agent=self.analytics_agent,
            recommendation_agent=self.recommendation_agent,
        )
        self.agent_loop = AgentLoopController()
        self.answer_review_agent = AnswerReviewAgent()
        # LLM callable — can be replaced in tests
        from app.rag.llm_client import generate_chat_completion as _llm
        self.llm_fn = _llm
        self._location_agent = None

    def get_location_agent(self):
        if self._location_agent is None:
            from app.rag.location_agent import ScenicLocationAgent
            self._location_agent = ScenicLocationAgent(self.fact_agent)
        return self._location_agent


# ---------------------------------------------------------------------------
# Node factories
# ---------------------------------------------------------------------------

def make_plan_node(ctx: NodeContext):
    def plan_node(state: GraphState) -> dict:
        user_query = state.get("user_query", "")
        scenic_slug = state.get("scenic_slug")
        conversation_context = state.get("conversation_context")
        session_memory = state.get("session_memory")
        start_attraction = state.get("start_attraction")

        plan = ctx.planner.plan(
            user_query,
            scenic_slug=scenic_slug,
            conversation_context=conversation_context,
            session_memory=session_memory,
        )

        # resolve context attraction
        context_attraction: Optional[str] = start_attraction
        if not context_attraction:
            memory_attraction = (session_memory or {}).get("last_attraction")
            if memory_attraction:
                context_attraction = str(memory_attraction)
            else:
                for item in reversed(list(conversation_context or [])):
                    meta = item.get("meta") if isinstance(item, dict) else None
                    if isinstance(meta, dict) and meta.get("matched_attraction"):
                        context_attraction = str(meta["matched_attraction"])
                        break
            if context_attraction:
                query = str(user_query or "")
                if context_attraction not in query and not REFERENCE_PRONOUN_PATTERN.search(query):
                    context_attraction = None

        patch: dict = {
            "plan": plan,
            "context_attraction": context_attraction,
            "intent": plan.intent,
        }

        # For fast-path strategies, resolve the reply here so finalize can use it directly.
        if plan.strategy in FAST_ANSWER_STRATEGIES:
            chat_reply = str(plan.chat_reply or "").strip()
            if not chat_reply:
                if plan.strategy == "refuse_off_topic":
                    chat_reply = _OFF_TOPIC_REPLY
                elif plan.strategy == "refuse_realtime":
                    chat_reply = _REALTIME_REPLY
                elif plan.strategy == "refuse_source_conflict":
                    chat_reply = _SOURCE_CONFLICT_REPLY
                elif plan.strategy == "ask_clarification":
                    chat_reply = _build_clarification_reply(
                        user_query,
                        question_type=plan.question_type,
                        scenic_slug=plan.scenic_slug or scenic_slug,
                    )
                else:
                    # general_chat fallback
                    chat_reply = "您好，有什么我可以帮您？"

            response_kind = {
                "refuse_off_topic": "refused:off_topic",
                "refuse_realtime": "refused:realtime_required",
                "refuse_source_conflict": "refused:source_conflict",
                "ask_clarification": "clarification",
                "general_chat": "chat",
            }.get(plan.strategy, "chat")

            patch["result"] = {
                "answer": chat_reply,
                "response_kind": response_kind,
                "evidence": [],
                "refusal": None,
                "warnings": [],
            }
            patch["agent_type"] = plan.strategy
            patch["response_kind"] = response_kind

        return patch
    return plan_node




def make_tool_dispatch_node(ctx: NodeContext):
    def tool_dispatch_node(state: GraphState) -> dict:
        plan = state["plan"]
        user_query = state.get("user_query", "")
        intent = state.get("intent", "FACT")
        user_profile = state.get("user_profile")
        context_attraction = state.get("context_attraction")
        scenic_slug = state.get("scenic_slug")
        attraction_id = state.get("attraction_id")
        forced_recommendation_profile = state.get("forced_recommendation_profile")
        forced_recommendation_title = state.get("forced_recommendation_title")

        strategy = plan.strategy

        def _fact_tool_call(tool_name: str, reason: str) -> ToolCall:
            return ToolCall(
                tool_name,
                {
                    "user_query": user_query,
                    "scenic_slug": plan.scenic_slug or scenic_slug,
                    "attraction_id": attraction_id,
                    "attraction_name": context_attraction,
                    "planned_question_type": plan.question_type,
                },
                reason=reason,
            )

        calls: List[ToolCall]

        # Detect "fact + analytics" parallel case: user query asks for both factual
        # information AND statistical analytics at the same time.  We recognise this
        # by looking for the raw_payload hint "parallel_fact_analytics" set by the
        # planner, OR by a heuristic: the plan carries ANALYTICS intent while the
        # query also contains scenic-fact keywords.
        raw_payload = getattr(plan, "raw_payload", {}) or {}
        is_parallel_fact_analytics = raw_payload.get("parallel_fact_analytics", False)

        if is_parallel_fact_analytics:
            # Fan-out: fire both a fact tool and the SQL analytics tool in parallel.
            tool_name = "hybrid_rag" if strategy == "hybrid_rag" else "structured_fact"
            fact_call = _fact_tool_call(tool_name, "planner_parallel_fact")
            sql_call = ToolCall(
                "behavior_sql",
                {"user_query": user_query},
                reason="planner_parallel_analytics",
            )
            calls = [fact_call, sql_call]
        elif strategy == "semantic_sql" or intent == "ANALYTICS":
            calls = [ToolCall("behavior_sql", {"user_query": user_query}, reason="planner_selected_semantic_sql")]
        elif strategy == "route_planner" or intent == "RECOMMEND":
            calls = [ToolCall(
                "route_planner",
                {
                    "user_query": user_query,
                    "start_attraction": context_attraction,
                    "user_profile": user_profile,
                    "scenic_slug": scenic_slug,
                    "forced_profile_key": forced_recommendation_profile or plan.route_profile,
                    "forced_title": forced_recommendation_title,
                },
                reason="planner_selected_route_planner",
            )]
        elif strategy == "web_search":
            calls = [ToolCall(
                "web_search",
                {"user_query": user_query},
                reason="planner_selected_web_search",
            )]
        else:
            tool_name = "hybrid_rag" if strategy == "hybrid_rag" else "structured_fact"
            calls = [_fact_tool_call(tool_name, f"planner_selected_{tool_name}")]

        first_step = AgentStep(
            action="call_tool",
            reason=calls[0].reason or "planner_selected_initial_tool",
            source="planner",
            tool_call=calls[0],
        )
        return {
            "candidate_tool_calls": calls,
            "agent_steps": [first_step],
            "tool_observations": [],
            "seen_tools": [],
            "tool_loop_count": 0,
        }
    return tool_dispatch_node


def make_tool_execute_node(ctx: NodeContext):
    def tool_execute_node(state: GraphState) -> dict:
        candidate_calls: list = state.get("candidate_tool_calls", [])
        seen_tools: list = list(state.get("seen_tools", []))

        if not candidate_calls:
            return {}

        call = candidate_calls[0]
        if call.name in seen_tools:
            stop_step = AgentStep(
                action="ask_clarification",
                reason=f"tool_already_called:{call.name}",
                source="agent_policy_fallback",
            )
            # Return only the new step; reducer appends it.
            # Don't return candidate_tool_calls here — agent_loop_decide will reset it.
            return {"agent_steps": [stop_step]}

        observation = ctx.tool_runner.run(call)

        # Return only the NEW items produced by this invocation. The Annotated
        # reducers on tool_observations, seen_tools, agent_steps, and
        # tool_loop_count will accumulate them correctly whether this node runs
        # sequentially or as one of several parallel Send branches.
        # candidate_tool_calls is intentionally omitted: agent_loop_decide always
        # resets it, and returning [] from two parallel branches would conflict.
        return {
            "tool_observations": [observation],
            "seen_tools": [call.name],
            "tool_loop_count": 1,
        }
    return tool_execute_node


def make_agent_loop_decide_node(ctx: NodeContext):
    def agent_loop_decide_node(state: GraphState) -> dict:
        user_query = state.get("user_query", "")
        plan = state["plan"]
        observations: list = state.get("tool_observations", [])
        seen_tools: list = state.get("seen_tools", [])

        # build candidate calls from last observation
        last_obs: Optional[ToolObservation] = observations[-1] if observations else None
        candidates: list = []
        if last_obs and last_obs.insufficient:
            suggested = set(last_obs.suggested_next_tools or [])
            user_profile = state.get("user_profile")
            context_attraction = state.get("context_attraction")
            scenic_slug = state.get("scenic_slug")
            attraction_id = state.get("attraction_id")
            forced_recommendation_profile = state.get("forced_recommendation_profile")
            forced_recommendation_title = state.get("forced_recommendation_title")

            def _fact_call(tool_name: str, reason: str) -> ToolCall:
                return ToolCall(
                    tool_name,
                    {
                        "user_query": user_query,
                        "scenic_slug": plan.scenic_slug or scenic_slug,
                        "attraction_id": attraction_id,
                        "attraction_name": context_attraction,
                        "planned_question_type": plan.question_type,
                    },
                    reason=reason,
                )

            if last_obs.tool_name == "structured_fact":
                candidates.append(_fact_call("hybrid_rag", "agent_observation_suggested_hybrid_rag"))
            if last_obs.tool_name == "behavior_sql" and (
                "hybrid_rag" in suggested or last_obs.response_kind in {"analytics:unresolved", "analytics:empty"}
            ):
                candidates.append(_fact_call("hybrid_rag", "agent_observation_suggested_hybrid_rag_after_sql"))
            if last_obs.tool_name == "route_planner" and ("structured_fact" in suggested or last_obs.insufficient):
                candidates.append(_fact_call("structured_fact", "agent_observation_suggested_structured_fact_after_route"))

        candidates = [c for c in candidates if c.name not in seen_tools]

        next_step = ctx.agent_loop.decide_next(
            user_query=user_query,
            plan=plan,
            observations=observations,
            candidate_calls=candidates,
        )

        next_candidates = []
        if next_step.action == "call_tool" and next_step.tool_call:
            next_candidates = [next_step.tool_call]

        # Return only the new step; the Annotated reducer on agent_steps appends it.
        return {
            "agent_steps": [next_step],
            "candidate_tool_calls": next_candidates,
        }
    return agent_loop_decide_node


def make_synthesize_node(ctx: NodeContext):
    """Selects the best observation and synthesizes a result dict."""

    def synthesize_node(state: GraphState) -> dict:
        user_query = state.get("user_query", "")
        plan = state["plan"]
        observations: list = state.get("tool_observations", [])
        agent_steps: list = state.get("agent_steps", [])
        conversation_context = state.get("conversation_context")
        session_memory = state.get("session_memory")
        context_attraction = state.get("context_attraction")

        # select final observation
        final_obs: Optional[ToolObservation] = None
        for obs in reversed(observations):
            if obs.ok and not obs.insufficient:
                final_obs = obs
                break
        if final_obs is None:
            for obs in reversed(observations):
                if obs.ok:
                    final_obs = obs
                    break
        if final_obs is None and observations:
            final_obs = observations[-1]

        if final_obs is None:
            return {
                "result": {"answer": "暂时无法回答，请重新描述您的问题。",
                           "response_kind": "clarification", "evidence": [], "refusal": None, "warnings": []},
                "agent_type": "dialog_agent",
                "trace": {},
            }

        result = dict(final_obs.result or {})
        result.setdefault("answer", final_obs.answer)
        result.setdefault("response_kind", final_obs.response_kind)
        result.setdefault("evidence", final_obs.evidence)
        result.setdefault("refusal", final_obs.refusal)
        result.setdefault("warnings", final_obs.warnings)

        if result.get("response_kind") == "structured_override":
            evidence_field = ""
            for item in result.get("evidence") or []:
                if isinstance(item, dict) and item.get("field"):
                    evidence_field = str(item["field"])
                    break
            result["response_kind"] = f"field:{evidence_field or plan.question_type or 'description'}"

        if final_obs.insufficient and not final_obs.refusal:
            result["answer"] = _build_clarification_reply(user_query, plan.question_type, plan.scenic_slug)
            result["response_kind"] = "clarification"
            result["refusal"] = None
            result["warnings"] = list(result.get("warnings") or []) + ["agent_tool_result_insufficient"]
        elif len(observations) > 1 and not state.get("repair_count", 0):
            supporting = [
                obs for obs in observations
                if obs is not final_obs and obs.ok and obs.evidence and not obs.insufficient
            ]
            if str(result.get("answer", "")).strip() and supporting:
                snippets = []
                for obs in [final_obs] + supporting[:2]:
                    snippets.append({
                        "tool": obs.tool_name,
                        "response_kind": obs.response_kind,
                        "answer": obs.answer[:600],
                        "evidence_count": len(obs.evidence or []),
                    })
                system_prompt = (
                    "You are the final answer composer for a scenic-guide agent. "
                    "Use only the supplied tool observations. Return concise Simplified Chinese only."
                )
                prompt = (
                    f"User query: {user_query}\n"
                    f"Planner strategy: {plan.strategy}, question_type: {plan.question_type}\n"
                    f"Tool observations: {json.dumps(snippets, ensure_ascii=False)}\n"
                    "Compose a natural final answer. Do not invent facts."
                )
                try:
                    synthesized = ctx.llm_fn(prompt, system_prompt=system_prompt,
                                             temperature=0.1, max_tokens=360, return_error_text=False)
                    synthesized = str(synthesized or "").strip().strip("\"'")
                    if synthesized and not synthesized.startswith("Error"):
                        result["answer"] = synthesized
                        result["warnings"] = list(result.get("warnings") or []) + ["agent_synthesized_from_tool_observations"]
                except Exception:
                    pass

        agent_type = _agent_type_for_tool(final_obs.tool_name)
        final_trace_from_result = dict(result.get("trace") or {})
        trace: Dict[str, Any] = {
            "conversation": {
                "used_context": bool(conversation_context or session_memory),
                "context_attraction": context_attraction,
            },
            "tools": {
                "available": [s["name"] for s in ToolRunner.specs()],
                "calls": [obs.to_trace() for obs in observations],
                "self_corrections": max(0, len(observations) - 1),
                "final_tool": observations[-1].tool_name if observations else None,
            },
            "agent_loop": {
                "steps": [step.to_trace() for step in agent_steps],
                "step_count": len(agent_steps),
            },
            "synthesis": {
                "source": "tool_observations",
                "observation_count": len(observations),
            },
        }
        analytics_trace = {
            "semantic_plan": result.get("semantic_plan"),
            "sql": result.get("sql"),
            "rows_preview": result.get("rows_preview"),
        }
        if result.get("semantic_plan") or result.get("sql") or result.get("rows_preview"):
            trace["analytics"] = analytics_trace
        trace.update(final_trace_from_result)

        return {
            "result": result,
            "agent_type": agent_type,
            "trace": trace,
        }
    return synthesize_node


def make_review_node(ctx: NodeContext):
    def review_node(state: GraphState) -> dict:
        user_query = state.get("user_query", "")
        result: dict = dict(state.get("result") or {})
        plan = state["plan"]
        agent_type = state.get("agent_type", "dialog_agent")
        trace: dict = dict(state.get("trace") or {})
        repair_history: list = list(state.get("repair_history") or [])

        audited = ctx.answer_review_agent.review(
            user_query=user_query,
            result={**result, "warnings": list(result.get("warnings") or []), "trace": trace},
            agent_type=agent_type,
            plan=plan,
        )
        warnings = list(audited.get("warnings") or [])
        result["warnings"] = warnings
        new_trace = audited.get("trace") if isinstance(audited.get("trace"), dict) else trace
        review = new_trace.get("answer_review") if isinstance(new_trace.get("answer_review"), dict) else {}

        return {
            "result": result,
            "trace": new_trace,
            "review_result": review,
            "repair_history": repair_history,
        }
    return review_node


def make_repair_execute_node(ctx: NodeContext):
    def repair_execute_node(state: GraphState) -> dict:
        user_query = state.get("user_query", "")
        plan = state["plan"]
        observations: list = list(state.get("tool_observations", []))
        repair_history: list = list(state.get("repair_history") or [])
        repair_count: int = state.get("repair_count", 0)
        review: dict = state.get("review_result") or {}
        trace: dict = dict(state.get("trace") or {})

        action = str(review.get("repair_action") or "none")
        seen_tools: list = state.get("seen_tools", [])
        context_attraction = state.get("context_attraction")
        scenic_slug = state.get("scenic_slug")
        attraction_id = state.get("attraction_id")
        user_profile = state.get("user_profile")
        forced_recommendation_profile = state.get("forced_recommendation_profile")
        forced_recommendation_title = state.get("forced_recommendation_title")

        final_obs: Optional[ToolObservation] = observations[-1] if observations else None

        def _fact_call(tool_name: str, reason: str) -> ToolCall:
            return ToolCall(
                tool_name,
                {
                    "user_query": user_query,
                    "scenic_slug": plan.scenic_slug or scenic_slug,
                    "attraction_id": attraction_id,
                    "attraction_name": context_attraction,
                    "planned_question_type": plan.question_type,
                },
                reason=reason,
            )

        candidate_calls: list = []
        if action in ("retry_same_agent", "retry") and final_obs:
            candidate_calls = [ToolCall(final_obs.tool_name, {"user_query": user_query}, reason=f"answer_review_repair:{action}")]
        elif "structured_fact" in action and "structured_fact" not in seen_tools:
            candidate_calls = [_fact_call("structured_fact", f"answer_review_repair:{action}")]
        elif "hybrid_rag" in action and "hybrid_rag" not in seen_tools:
            candidate_calls = [_fact_call("hybrid_rag", f"answer_review_repair:{action}")]
        elif "behavior_sql" in action and "behavior_sql" not in seen_tools:
            candidate_calls = [ToolCall("behavior_sql", {"user_query": user_query}, reason=f"answer_review_repair:{action}")]
        elif "route_planner" in action and "route_planner" not in seen_tools:
            candidate_calls = [ToolCall(
                "route_planner",
                {"user_query": user_query, "start_attraction": context_attraction, "user_profile": user_profile,
                 "scenic_slug": scenic_slug, "forced_profile_key": forced_recommendation_profile or plan.route_profile,
                 "forced_title": forced_recommendation_title},
                reason=f"answer_review_repair:{action}",
            )]
        # Primary tool already seen — offer all unseen fact tools so LLM can pick one
        if not candidate_calls:
            for fallback_tool in ("hybrid_rag", "structured_fact"):
                if fallback_tool not in seen_tools:
                    candidate_calls.append(_fact_call(fallback_tool, f"answer_review_repair:fallback_{fallback_tool}"))

        repair_step = ctx.agent_loop.decide_repair_from_review(
            user_query=user_query, plan=plan, observations=observations,
            review=review, candidate_calls=candidate_calls,
        )

        if repair_step.action != "call_tool" or not repair_step.tool_call:
            repair_history.append({"attempt": repair_count + 1, "action": action, "status": "no_repair_tool",
                                    "agent_step": repair_step.to_trace()})
            trace["answer_review_repair"] = repair_history
            # Return only the new step; reducer appends it.
            return {"agent_steps": [repair_step], "repair_history": repair_history, "trace": trace,
                    "repair_count": repair_count + 1, "candidate_tool_calls": []}

        repair_call = repair_step.tool_call
        if repair_call.name in seen_tools:
            repair_history.append({"attempt": repair_count + 1, "action": action, "status": "tool_already_called",
                                    "agent_step": repair_step.to_trace()})
            trace["answer_review_repair"] = repair_history
            return {"agent_steps": [repair_step], "repair_history": repair_history, "trace": trace,
                    "repair_count": repair_count + 1, "candidate_tool_calls": []}

        new_obs = ctx.tool_runner.run(repair_call)
        repair_history.append({
            "attempt": repair_count + 1,
            "action": action,
            "status": "repaired",
            "agent_step": repair_step.to_trace(),
            "agent_step_source": repair_step.source,
            "tool_name": repair_call.name,
            "tool": repair_call.name,
        })

        return {
            "tool_observations": [new_obs],
            "agent_steps": [repair_step],
            "seen_tools": [repair_call.name],
            "repair_count": repair_count + 1,
            "repair_history": repair_history,
            "trace": trace,
            "candidate_tool_calls": [],
        }
    return repair_execute_node


def make_finalize_node(ctx: NodeContext):
    from app.core.runtime import merge_runtime_status, utc_timestamp

    def finalize_node(state: GraphState) -> dict:
        latency_start: float = state.get("latency_start", time.perf_counter())
        user_query = state.get("user_query", "")
        intent = state.get("intent", "CHAT")
        agent_type = state.get("agent_type", "dialog_agent")
        plan = state.get("plan")
        result: dict = dict(state.get("result") or {})
        trace: dict = dict(state.get("trace") or {})
        repair_history: list = state.get("repair_history") or []

        answer = result.get("answer", "")
        response_kind = result.get("response_kind", "fact")
        evidence = result.get("evidence") or []
        refusal = result.get("refusal")
        warnings: list = list(result.get("warnings") or [])
        recommendation = result.get("recommendation")
        matched_attraction = result.get("matched_attraction")
        recommendation_label = result.get("recommendation_label")

        if not recommendation_label and agent_type == "scenic_recommendation":
            recommendation_label = extract_interest_label(user_query)

        if repair_history:
            trace["answer_review_repair"] = repair_history

        latency_ms = round((time.perf_counter() - latency_start) * 1000, 2)

        if plan is None:
            plan = SimpleNamespace(strategy="general_chat", question_type=None, route_profile=None,
                                   confidence=1.0, reasoning=[], scenic_slug=None,
                                   planner_source="none", raw_payload={})

        payload = {
            "final_answer": answer,
            "response_kind": response_kind,
            "evidence": evidence,
            "refusal": refusal,
            "warnings": warnings,
            "recommendation": recommendation,
            "matched_attraction": matched_attraction,
            "recommendation_label": recommendation_label,
            "intent": intent,
            "agent_type": agent_type,
            "trace": trace,
            "finalized_plan": _plan_payload(plan),
            "latency_ms": latency_ms,
            "tts_style": _infer_tts_style(ctx.llm_fn, answer),
        }

        compact = {
            "query": str(user_query)[:160],
            "intent": intent,
            "agent_type": agent_type,
            "response_kind": response_kind,
            "strategy": _plan_payload(plan).get("strategy"),
            "latency_ms": latency_ms,
            "evidence_count": len(evidence),
            "refusal_reason": (refusal or {}).get("reason"),
            "warnings": warnings[:5],
        }
        merge_runtime_status({"last_query_trace": compact})

        return payload
    return finalize_node



# ---------------------------------------------------------------------------
# TTS style inference
# ---------------------------------------------------------------------------

EDGE_TTS_STYLES = frozenset({
    "assistant", "calm", "chat", "cheerful", "customerservice",
    "depressed", "disgruntled", "documentary-narration", "embarrassed",
    "empathetic", "fearful", "friendly", "gentle", "lyrical",
    "newscast", "poetry-reading", "sad", "serious", "sorry", "whisper",
})
TTS_STYLE_FALLBACK = "gentle"
_STYLES_STR = ", ".join(sorted(EDGE_TTS_STYLES))


def _infer_tts_style(llm_fn, answer: str) -> str:
    if not answer or not answer.strip():
        return TTS_STYLE_FALLBACK
    prompt = (
        f"你是语音助手情绪分类器。根据以下导览回答，从列表中选择最合适的一个语气风格，"
        f"只输出该词，不要有其他内容。\n"
        f"可选风格：{_STYLES_STR}\n"
        f"回答文本：{answer[:300]}"
    )
    try:
        raw = llm_fn(
            prompt,
            system_prompt="Only output one word from the allowed list. No explanation.",
            temperature=0.0,
            max_tokens=15,
            return_error_text=False,
        )
        candidate = str(raw or "").strip().strip("\"'. ").lower()
        if candidate in EDGE_TTS_STYLES:
            return candidate
    except Exception:
        pass
    return TTS_STYLE_FALLBACK


# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------

FAST_ANSWER_STRATEGIES = {"general_chat", "ask_clarification", "refuse_realtime", "refuse_source_conflict", "refuse_off_topic"}

_OFF_TOPIC_REPLY = "抱歉，这超出了我的服务范围。我是景区导游助手，可以帮您查景点介绍、规划路线或了解景区文化。"
_REALTIME_REPLY = "抱歉，这需要实时或外部数据支持，我目前无法获取。可以帮您了解景区历史均值数据或景点讲解。"
_SOURCE_CONFLICT_REPLY = "抱歉，这个问题要求用不匹配的数据源回答，我无法提供准确结果。"


def route_after_plan(state: GraphState) -> str:
    plan = state.get("plan")
    if plan is None:
        return "finalize"
    if plan.strategy in FAST_ANSWER_STRATEGIES:
        return "finalize"
    return "tool_dispatch"


def route_after_tool_dispatch(state: GraphState) -> Union[str, List[Send]]:
    """Fan-out to parallel tool_execute nodes when multiple calls are queued."""
    calls: list = state.get("candidate_tool_calls", [])
    if len(calls) > 1:
        # Each Send carries the full state but with only one tool call to execute.
        return [Send("tool_execute", {**state, "candidate_tool_calls": [call]}) for call in calls]
    return "tool_execute"


def route_after_agent_loop_decide(state: GraphState) -> str:
    agent_steps: list = state.get("agent_steps", [])
    tool_loop_count: int = state.get("tool_loop_count", 0)
    if not agent_steps:
        return "synthesize"
    last_step = agent_steps[-1]
    if last_step.action == "call_tool" and last_step.tool_call and tool_loop_count < 3:
        return "tool_execute"
    return "synthesize"


def route_after_review(state: GraphState) -> str:
    review: dict = state.get("review_result") or {}
    repair_count: int = state.get("repair_count", 0)
    if review.get("checked") is False:
        return "finalize"
    if review.get("approved", True) or repair_count >= 2:
        return "finalize"
    action = str(review.get("repair_action") or "none")
    if action == "none":
        return "finalize"
    return "repair_execute"


def route_after_repair(state: GraphState) -> str:
    repair_count: int = state.get("repair_count", 0)
    candidate_calls: list = state.get("candidate_tool_calls") or []
    if repair_count >= 2 or not candidate_calls:
        return "synthesize"
    return "synthesize"
