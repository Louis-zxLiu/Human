from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

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

def _fallback_general_chat_reply(user_query: str) -> Optional[str]:
    query = re.sub(r"\s+", "", str(user_query or "")).lower()
    if not query:
        return None
    if re.fullmatch(r"(你好|您好|嗨|哈喽|hello|hi|早上好|中午好|下午好|晚上好)[!,.?~]*", query, re.IGNORECASE):
        return "你好，我在。"
    if re.fullmatch(r"(在吗|在不在|有人吗)[!,.?~]*", query, re.IGNORECASE):
        return "在，你说。"
    if re.fullmatch(r"(谢谢|多谢|感谢你|谢了)[!,.?~]*", query, re.IGNORECASE):
        return "不客气，我在。"
    if re.fullmatch(r"(再见|拜拜|bye|goodbye)[!,.?~]*", query, re.IGNORECASE):
        return "好，随时叫我。"
    if re.fullmatch(r"(你是谁|你是干嘛的|你能做什么|介绍一下你自己)[!,.?~]*", query):
        return "我是景区导览助手，可以陪你聊天，也可以帮你查景点介绍、规划路线、分析游客行为数据。"
    if re.fullmatch(r"(好的|好哦|收到|明白了|嗯嗯|行|ok|okay)[!,.?~]*", query, re.IGNORECASE):
        return "好的。"
    return None


def _normalize_general_chat_reply(reply: str, fallback: str, max_chars: int = 80) -> str:
    normalized = re.sub(r"\s+", " ", str(reply or "")).strip().strip("\"'")
    if not normalized:
        return fallback
    parts = [p.strip() for p in re.split(r"(?<=[。！？!?])", normalized) if p.strip()]
    short_reply = "".join(parts[:2]) if parts else normalized
    if len(short_reply) > max_chars:
        short_reply = short_reply[:max_chars].rstrip("，。！？!? ")
    return short_reply or fallback


def _build_clarification_reply(user_query: str, question_type: Optional[str] = None, scenic_slug: Optional[str] = None) -> str:
    query = str(user_query or "")
    if question_type == "highlights":
        return "可以，我先帮你缩小范围。你想了解哪个景点的看点？也可以告诉我你偏自然风光、历史文化、亲子还是拍照打卡。"
    if question_type in ("route", "route_planner"):
        return "可以规划。你从哪个位置出发，同行有没有老人或孩子，想轻松逛还是多看几个核心景点？"
    if scenic_slug:
        return "可以介绍。你想了解哪个具体景点？如果还没确定，我可以先从代表性景点、历史文化、主要看点或游览建议里选一个方向讲。"
    return "可以介绍。你想了解哪个城市、景区或具体景点？如果还没确定，也可以告诉我偏自然风光、历史文化、亲子游还是拍照打卡。"


def _is_pure_social_chat(user_query: str) -> bool:
    """LLM-free fast check: only matches unambiguous one-line social utterances."""
    query = re.sub(r"\s+", "", str(user_query or "")).lower()
    return bool(re.fullmatch(
        r"(你好|您好|嗨|哈喽|hello|hi|早上好|中午好|下午好|晚上好|在吗|在不在|有人吗"
        r"|谢谢|多谢|感谢你|谢了|再见|拜拜|bye|goodbye|好的|好哦|收到|明白了|嗯嗯|行|ok|okay"
        r"|你是谁|你是干嘛的|你能做什么|介绍一下你自己)[!,.?~]*",
        query, re.IGNORECASE,
    ))


def _should_screen_general_chat(user_query: str, fallback_reply: Optional[str]) -> bool:
    """Return True when the query is safe to handle as general_chat without RAG."""
    if fallback_reply:
        return True
    return _is_pure_social_chat(user_query)


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

        return {
            "plan": plan,
            "context_attraction": context_attraction,
            "intent": plan.intent,
        }
    return plan_node


def make_fast_answer_node(ctx: NodeContext):
    """Handles general_chat / ask_clarification / refuse_* strategies directly."""

    def fast_answer_node(state: GraphState) -> dict:
        plan = state["plan"]
        user_query = state.get("user_query", "")
        scenic_slug = state.get("scenic_slug")
        intent = state.get("intent", "CHAT")

        strategy = plan.strategy

        if strategy == "general_chat":
            # Queries asking about another visitor's realtime position by ID should be refused,
            # even if planner mis-routed them to general_chat.
            import re as _re2
            if _re2.search(r'\bU\d{3,}\b', user_query) and any(
                w in user_query for w in ('在哪', '位置', '能回答', '能定位', '现在')
            ):
                _ref2 = make_refusal(
                    "realtime_required",
                    message="系统无法追踪其他游客的实时位置，没有 GPS 或视觉定位能力。",
                    suggested_queries=["可以描述您周围的地标，我来帮您推断您自己的位置"],
                )
                return {
                    "result": {"answer": "抱歉，系统没有 GPS 或实时追踪能力，无法判断其他游客的当前位置。如果您想知道自己在哪，可以描述周围的地标，我来帮您推断。",
                               "response_kind": "refused:realtime_required",
                               "evidence": [], "refusal": _ref2, "warnings": []},
                    "agent_type": "query_planner",
                    "response_kind": "refused:realtime_required",
                }
            fallback_chat_reply = _fallback_general_chat_reply(user_query)

            # For unambiguous social utterances use the fast fallback directly.
            if fallback_chat_reply and _is_pure_social_chat(user_query):
                screened_chat_reply = fallback_chat_reply
            else:
                # Use LLM to verify this is really general chat and get a reply.
                fallback = fallback_chat_reply or "你好，我在。"
                screened_chat_reply = None
                system_prompt = (
                    "You classify whether a message to a scenic-guide assistant is ordinary conversation. "
                    "Return strict JSON only. "
                    'Use {"is_general_chat": true, "reply": "..."} for greetings, thanks, '
                    "goodbyes, simple acknowledgements, asking who the assistant is, or other brief social talk. "
                    'Use {"is_general_chat": false} for scenic facts, route recommendations, '
                    "navigation, weather, traffic, opening info, or any domain task. "
                    "If is_general_chat is true, reply in concise Simplified Chinese, warm and natural, under 24 Chinese characters."
                )
                try:
                    raw = ctx.llm_fn(
                        f"User message: {user_query}\nReturn JSON only.",
                        system_prompt, temperature=0.0, max_tokens=160,
                        return_error_text=False, json_mode=True,
                    )
                    cleaned = str(raw or "").replace("```json", "").replace("```", "").strip()
                    if cleaned:
                        payload = json.loads(cleaned)
                        if payload.get("is_general_chat") is True:
                            screened_chat_reply = _normalize_general_chat_reply(
                                str(payload.get("reply") or ""), fallback, max_chars=80)
                        elif payload.get("is_general_chat") is False:
                            screened_chat_reply = None
                except Exception:
                    pass
                if screened_chat_reply is None:
                    screened_chat_reply = fallback_chat_reply or "你好，我在。"

            fast_plan = SimpleNamespace(
                strategy="general_chat", question_type=None, route_profile=None,
                confidence=1.0, reasoning=plan.reasoning, scenic_slug=scenic_slug,
                planner_source=plan.planner_source, raw_payload=plan.raw_payload,
            )
            return {
                "result": {"answer": screened_chat_reply, "response_kind": "chat",
                           "evidence": [], "refusal": None, "warnings": []},
                "plan": fast_plan,
                "agent_type": "general_chat",
                "response_kind": "chat",
            }

        if strategy == "ask_clarification":
            # Location-type clarification: try to infer position from landmark description first.
            # Only fall back to a follow-up question if no candidates match.
            if plan.question_type == "location":
                # Queries asking about another visitor's position by ID (e.g. "U99999现在在哪")
                # cannot be answered — system has no GPS or tracking capability.
                import re as _re
                if _re.search(r'\bU\d{3,}\b', user_query):
                    _ref = make_refusal(
                        "realtime_required",
                        message="系统无法追踪其他游客的实时位置，没有 GPS 或视觉定位能力。",
                        suggested_queries=["可以描述您周围的地标，我来帮您推断您自己的位置"],
                    )
                    return {
                        "result": {"answer": "抱歉，系统没有 GPS 或实时追踪能力，无法判断其他游客的当前位置。如果您想知道自己在哪，可以描述周围的地标，我来帮您推断。",
                                   "response_kind": "refused:realtime_required",
                                   "evidence": [], "refusal": _ref, "warnings": []},
                        "agent_type": "query_planner",
                        "response_kind": "refused:realtime_required",
                    }
                location_agent = ctx.get_location_agent()
                candidates = location_agent.infer_candidates(
                    user_query, scenic_slug=plan.scenic_slug or scenic_slug
                )
                gps_result = location_agent.build_candidate_reply(candidates, user_query)
                gps_state = gps_result["gps_state"]
                if gps_state == "resolved":
                    resolved = gps_result["resolved_attraction"]
                    answer = gps_result["answer"]
                    return {
                        "result": {"answer": answer, "response_kind": "gps:resolved",
                                   "evidence": [], "refusal": None, "warnings": []},
                        "agent_type": "location_agent",
                        "response_kind": "gps:resolved",
                        "matched_attraction": resolved,
                    }
                elif gps_state == "ambiguous":
                    answer = gps_result["answer"]
                    return {
                        "result": {"answer": answer, "response_kind": "gps:ambiguous",
                                   "evidence": [], "refusal": None, "warnings": []},
                        "agent_type": "location_agent",
                        "response_kind": "gps:ambiguous",
                        "gps_candidates": gps_result.get("candidate_names", []),
                    }
                else:
                    # need_more_landmarks — ask follow-up
                    answer = location_agent.build_follow_up_prompt()
                    return {
                        "result": {"answer": answer, "response_kind": "gps:need_more_landmarks",
                                   "evidence": [], "refusal": None, "warnings": []},
                        "agent_type": "location_agent",
                        "response_kind": "gps:need_more_landmarks",
                    }

            answer = _normalize_general_chat_reply(
                plan.chat_reply,
                _build_clarification_reply(user_query, plan.question_type, plan.scenic_slug or scenic_slug),
                max_chars=96,
            )
            return {
                "result": {"answer": answer, "response_kind": "clarification",
                           "evidence": [], "refusal": None, "warnings": []},
                "agent_type": "dialog_agent",
                "response_kind": "clarification",
            }

        if strategy == "refuse_realtime":
            answer = (
                "抱歉，这个问题需要实时运营数据或未来信息支持。"
                "我不能根据当前离线知识资料和游客行为样本编造结果。"
                "您可以改问景点事实、历史文化、推荐路线，或基于游客行为数据的统计分析。"
            )
            refusal = make_refusal(
                "realtime_required",
                message="当前系统只支持离线事实、离线文档知识和历史行为分析。",
                suggested_queries=["今天的客流需要接入实时系统后再问", "可以先问景点事实、历史文化或游客偏好分析"],
            )
            return {
                "result": {"answer": answer, "response_kind": "refused:realtime_required",
                           "evidence": [], "refusal": refusal, "warnings": []},
                "agent_type": "query_planner",
                "response_kind": "refused:realtime_required",
            }

        # refuse_source_conflict
        answer = (
            "抱歉，这个问题混用了不合适的数据源。"
            "游客行为数据只能用于统计分析，景区资料只能用于事实、历史文化和讲解内容。"
            "请拆开提问，我再分别回答。"
        )
        refusal = make_refusal(
            "source_conflict",
            message="事实问答和行为分析需要分别求解。",
            suggested_queries=["请单独问景点事实问题", "请单独问游客行为统计问题"],
        )
        return {
            "result": {"answer": answer, "response_kind": "refused:source_conflict",
                       "evidence": [], "refusal": refusal, "warnings": []},
            "agent_type": "query_planner",
            "response_kind": "refused:source_conflict",
        }
    return fast_answer_node


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
        if strategy == "semantic_sql" or intent == "ANALYTICS":
            first_call = ToolCall("behavior_sql", {"user_query": user_query}, reason="planner_selected_semantic_sql")
        elif strategy == "route_planner" or intent == "RECOMMEND":
            first_call = ToolCall(
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
            )
        elif strategy == "web_search":
            first_call = ToolCall(
                "web_search",
                {"user_query": user_query},
                reason="planner_selected_web_search",
            )
        else:
            tool_name = "hybrid_rag" if strategy == "hybrid_rag" else "structured_fact"
            first_call = ToolCall(
                tool_name,
                {
                    "user_query": user_query,
                    "scenic_slug": plan.scenic_slug or scenic_slug,
                    "attraction_id": attraction_id,
                    "attraction_name": context_attraction,
                    "planned_question_type": plan.question_type,
                },
                reason=f"planner_selected_{tool_name}",
            )

        first_step = AgentStep(
            action="call_tool",
            reason=first_call.reason or "planner_selected_initial_tool",
            source="planner",
            tool_call=first_call,
        )
        return {
            "candidate_tool_calls": [first_call],
            "agent_steps": [first_step],
            "tool_observations": [],
            "seen_tools": [],
            "tool_loop_count": 0,
        }
    return tool_dispatch_node


def make_tool_execute_node(ctx: NodeContext):
    def tool_execute_node(state: GraphState) -> dict:
        candidate_calls: list = state.get("candidate_tool_calls", [])
        observations: list = list(state.get("tool_observations", []))
        agent_steps: list = list(state.get("agent_steps", []))
        seen_tools: list = list(state.get("seen_tools", []))
        loop_count: int = state.get("tool_loop_count", 0)

        if not candidate_calls:
            return {}

        call = candidate_calls[0]
        if call.name in seen_tools:
            stop_step = AgentStep(
                action="ask_clarification",
                reason=f"tool_already_called:{call.name}",
                source="agent_policy_fallback",
            )
            agent_steps.append(stop_step)
            return {"agent_steps": agent_steps, "candidate_tool_calls": []}

        seen_tools.append(call.name)
        observation = ctx.tool_runner.run(call)
        observations.append(observation)

        return {
            "tool_observations": observations,
            "seen_tools": seen_tools,
            "tool_loop_count": loop_count + 1,
            "candidate_tool_calls": candidate_calls[1:],
            "agent_steps": agent_steps,
        }
    return tool_execute_node


def make_agent_loop_decide_node(ctx: NodeContext):
    def agent_loop_decide_node(state: GraphState) -> dict:
        user_query = state.get("user_query", "")
        plan = state["plan"]
        observations: list = state.get("tool_observations", [])
        agent_steps: list = list(state.get("agent_steps", []))
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
        agent_steps.append(next_step)

        next_candidates = []
        if next_step.action == "call_tool" and next_step.tool_call:
            next_candidates = [next_step.tool_call]

        return {
            "agent_steps": agent_steps,
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
        agent_steps: list = list(state.get("agent_steps", []))
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
        agent_steps.append(repair_step)

        if repair_step.action != "call_tool" or not repair_step.tool_call:
            repair_history.append({"attempt": repair_count + 1, "action": action, "status": "no_repair_tool",
                                    "agent_step": repair_step.to_trace()})
            trace["answer_review_repair"] = repair_history
            return {"agent_steps": agent_steps, "repair_history": repair_history, "trace": trace,
                    "repair_count": repair_count + 1, "candidate_tool_calls": []}

        repair_call = repair_step.tool_call
        if repair_call.name in seen_tools:
            repair_history.append({"attempt": repair_count + 1, "action": action, "status": "tool_already_called",
                                    "agent_step": repair_step.to_trace()})
            trace["answer_review_repair"] = repair_history
            return {"agent_steps": agent_steps, "repair_history": repair_history, "trace": trace,
                    "repair_count": repair_count + 1, "candidate_tool_calls": []}

        new_obs = ctx.tool_runner.run(repair_call)
        observations.append(new_obs)
        seen_tools_new = list(seen_tools) + [repair_call.name]
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
            "tool_observations": observations,
            "agent_steps": agent_steps,
            "seen_tools": seen_tools_new,
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

FAST_ANSWER_STRATEGIES = {"general_chat", "ask_clarification", "refuse_realtime", "refuse_source_conflict"}


def route_after_plan(state: GraphState) -> str:
    plan = state.get("plan")
    if plan is None:
        return "finalize"
    if plan.strategy in FAST_ANSWER_STRATEGIES:
        return "fast_answer"
    return "tool_dispatch"


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
