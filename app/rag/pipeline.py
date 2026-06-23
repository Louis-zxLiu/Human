import json
import re
import time
from types import SimpleNamespace
from typing import Any, Dict, Optional

from app.core.runtime import merge_runtime_status, utc_timestamp
from app.rag.agent_loop import AgentLoopController, AgentStep
from app.rag.answer_review_agent import AnswerReviewAgent
from app.rag.fact_agent import ScenicFactAgent, extract_interest_label
from app.rag.llm_client import generate_chat_completion
from app.rag.planner import QueryPlanner
from app.rag.recommendation_agent import ScenicRecommendationAgent
from app.rag.response_contract import make_refusal
from app.rag.sql_agent import TouristAnalyticsAgent
from app.rag.tool_runner import ToolCall, ToolObservation, ToolRunner

REFERENCE_PRONOUN_PATTERN = re.compile(r"(它|这里|这个景点|这个地方|刚才那个|刚刚那个|上一个|这个)")


GENERAL_CHAT_EXACT_PATTERNS = (
    re.compile(r"^(?:你好|您好|嗨|哈喽|hello|hi)[!,.?~\s]*$", re.IGNORECASE),
    re.compile(r"^(?:早上好|中午好|下午好|晚上好)[!,.?~\s]*$", re.IGNORECASE),
    re.compile(r"^(?:在吗|在不在|有人吗)[!,.?~\s]*$", re.IGNORECASE),
    re.compile(r"^(?:谢谢|多谢|感谢你|谢了)[!,.?~\s]*$", re.IGNORECASE),
    re.compile(r"^(?:再见|拜拜|bye|goodbye)[!,.?~\s]*$", re.IGNORECASE),
    re.compile(r"^(?:你是谁|你是干嘛的|你能做什么|介绍一下你自己)[!,.?~\s]*$"),
    re.compile(r"^(?:好的|好哦|收到|明白了|嗯嗯|行|ok|okay)[!,.?~\s]*$", re.IGNORECASE),
)


GENERAL_CHAT_DOMAIN_SIGNALS = (
    "灵山",
    "拈花湾",
    "梵宫",
    "大佛",
    "景区",
    "景点",
    "路线",
    "推荐",
    "介绍",
    "讲解",
    "位置",
    "在哪",
    "哪里",
    "怎么走",
    "导航",
    "开放",
    "门票",
    "天气",
    "停车",
    "客流",
    "排队",
)


def _should_screen_general_chat(user_query: str, fallback_reply: Optional[str]) -> bool:
    query = str(user_query or "").strip()
    if not query:
        return False
    if fallback_reply:
        return True
    if len(query) > 18:
        return False
    return not any(signal in query for signal in GENERAL_CHAT_DOMAIN_SIGNALS)


def _fallback_general_chat_reply(user_query: str) -> Optional[str]:
    query = re.sub(r"\s+", "", str(user_query or "")).lower()
    if not query:
        return None
    if re.fullmatch(r"(你好|您好|嗨|哈喽|hello|hi|早上好|中午好|下午好|晚上好)[!,.?~]*", query, re.IGNORECASE):
        return "\u4f60\u597d\uff0c\u6211\u5728\u3002"
    if re.fullmatch(r"(在吗|在不在|有人吗)[!,.?~]*", query, re.IGNORECASE):
        return "\u5728\uff0c\u4f60\u8bf4\u3002"
    if re.fullmatch(r"(谢谢|多谢|感谢你|谢了)[!,.?~]*", query, re.IGNORECASE):
        return "\u4e0d\u5ba2\u6c14\uff0c\u6211\u5728\u3002"
    if re.fullmatch(r"(再见|拜拜|bye|goodbye)[!,.?~]*", query, re.IGNORECASE):
        return "\u597d\uff0c\u968f\u65f6\u53eb\u6211\u3002"
    if re.fullmatch(r"(你是谁|你是干嘛的|你能做什么|介绍一下你自己)[!,.?~]*", query):
        return "我是景区导览助手，可以陪你聊天，也可以帮你查景点介绍、规划路线、分析游客行为数据。"
    if re.fullmatch(r"(好的|好哦|收到|明白了|嗯嗯|行|ok|okay)[!,.?~]*", query, re.IGNORECASE):
        return "\u597d\u7684\u3002"
    if any(pattern.fullmatch(str(user_query or "").strip()) for pattern in GENERAL_CHAT_EXACT_PATTERNS):
        return "\u4f60\u8bf4\uff0c\u6211\u5728\u542c\u3002"
    return None


def _looks_like_non_social_task(user_query: str) -> bool:
    query = re.sub(r"\s+", "", str(user_query or ""))
    if not query:
        return False
    task_terms = (
        "\u662f\u4ec0\u4e48",
        "\u5728\u54ea",
        "\u54ea\u91cc",
        "\u600e\u4e48",
        "\u600e\u6837",
        "\u591a\u5c11",
        "\u51e0",
        "\u54ea\u4e2a",
        "\u4ecb\u7ecd",
        "\u63a8\u8350",
        "\u8def\u7ebf",
        "\u666f\u70b9",
        "\u666f\u533a",
        "\u6e38\u5ba2",
        "\u6570\u636e",
        "\u7edf\u8ba1",
        "\u5206\u6790",
        "浠€涔",
        "鍦ㄥ摢",
        "鍝噷",
        "鎬庝箞",
        "澶氬皯",
        "鍝釜",
        "浠嬬粛",
        "鎺ㄨ崘",
        "璺嚎",
        "鏅偣",
        "鏅尯",
        "娓稿",
        "鏁版嵁",
        "缁熻",
        "鍒嗘瀽",
    )
    return any(term in query for term in task_terms)


def _normalize_general_chat_reply(reply: str, fallback: str, max_chars: int = 80) -> str:
    normalized = re.sub(r"\s+", " ", str(reply or "")).strip().strip("\"'")
    if not normalized:
        return fallback
    parts = [part.strip() for part in re.split(r"(?<=[。！？!?])", normalized) if part.strip()]
    short_reply = "".join(parts[:2]) if parts else normalized
    if len(short_reply) > max_chars:
        short_reply = short_reply[:max_chars].rstrip("，。！？!? ")
    return short_reply or fallback


def _build_clarification_reply(user_query: str, question_type: Optional[str] = None, scenic_slug: Optional[str] = None) -> str:
    query = str(user_query or "")
    if question_type == "highlights" or any(term in query for term in ("好玩", "好看", "看点", "亮点", "特色")):
        return "可以，我先帮你缩小范围。你想了解哪个景点的看点？也可以告诉我你偏自然风光、历史文化、亲子还是拍照打卡。"
    if any(term in query for term in ("路线", "怎么逛", "怎么走", "安排", "规划")):
        return "可以规划。你从哪个位置出发，同行有没有老人或孩子，想轻松逛还是多看几个核心景点？"
    if scenic_slug:
        return "可以介绍。你想了解哪个具体景点？如果还没确定，我可以先从代表性景点、历史文化、主要看点或游览建议里选一个方向讲。"
    return "可以介绍。你想了解哪个城市、景区或具体景点？如果还没确定，也可以告诉我偏自然风光、历史文化、亲子游还是拍照打卡。"


def _last_attraction_from_context(
    conversation_context: Optional[list[Dict[str, Any]]] = None,
    session_memory: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    memory_attraction = (session_memory or {}).get("last_attraction")
    if memory_attraction:
        return str(memory_attraction)
    for item in reversed(list(conversation_context or [])):
        meta = item.get("meta") if isinstance(item, dict) else None
        if isinstance(meta, dict) and meta.get("matched_attraction"):
            return str(meta["matched_attraction"])
    return None


def _resolve_context_attraction(
    user_query: str,
    explicit_start: Optional[str],
    conversation_context: Optional[list[Dict[str, Any]]] = None,
    session_memory: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    if explicit_start:
        return explicit_start
    last_attraction = _last_attraction_from_context(conversation_context, session_memory)
    if not last_attraction:
        return None
    query = str(user_query or "")
    if last_attraction in query or REFERENCE_PRONOUN_PATTERN.search(query):
        return last_attraction
    return None


def detect_general_chat_reply(user_query: str) -> Optional[str]:
    query = str(user_query or "").strip()
    if not query:
        return None

    fallback_reply = _fallback_general_chat_reply(query)
    if not _should_screen_general_chat(query, fallback_reply):
        return None

    system_prompt = (
        "You classify whether a message to a scenic-guide assistant is ordinary conversation. "
        "Return strict JSON only. "
        'Use {"is_general_chat": true, "reply": "...", "reason": "..."} for greetings, thanks, '
        "goodbyes, simple acknowledgements, asking who the assistant is, or other brief social talk. "
        'Use {"is_general_chat": false, "reason": "..."} for scenic facts, route recommendations, '
        "navigation, weather, traffic, opening info, or any domain task. "
        "If is_general_chat is true, reply in concise Simplified Chinese, warm and natural, under 24 Chinese characters, "
        "and do not mention missing data or refusal."
    )
    prompt = (
        f"User message: {query}\n"
        'Examples:\n'
        '- "你好" => {"is_general_chat": true, "reply": "你好，我在。", "reason": "greeting"}\n'
        '- "谢谢" => {"is_general_chat": true, "reply": "不客气，我在。", "reason": "thanks"}\n'
        '- "你是谁" => {"is_general_chat": true, "reply": "我是景区导览助手。", "reason": "identity"}\n'
        '- "灵山大佛在哪里" => {"is_general_chat": false, "reason": "scenic fact"}\n'
        '- "推荐一条路线" => {"is_general_chat": false, "reason": "recommendation"}\n'
        '- "今天天气怎么样" => {"is_general_chat": false, "reason": "realtime"}\n'
        "Return JSON only."
    )

    try:
        raw = generate_chat_completion(
            prompt,
            system_prompt,
            temperature=0.0,
            max_tokens=160,
            return_error_text=False,
            json_mode=True,
        )
        cleaned = str(raw or "").replace("```json", "").replace("```", "").strip()
        if cleaned:
            payload = json.loads(cleaned)
            if payload.get("is_general_chat") is True:
                return _normalize_general_chat_reply(
                    str(payload.get("reply") or ""),
                    fallback_reply or "\u4f60\u597d\uff0c\u6211\u5728\u3002",
                )
            if payload.get("is_general_chat") is False:
                return None
    except Exception:
        pass

    return fallback_reply


class ScenicRAGPipeline:
    """Unified runtime pipeline for FACT / ANALYTICS / RECOMMEND."""

    def __init__(self):
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

    def process_query(
        self,
        user_query: str,
        user_profile: Optional[str] = None,
        start_attraction: Optional[str] = None,
        scenic_slug: Optional[str] = None,
        attraction_id: Optional[str] = None,
        forced_recommendation_profile: Optional[str] = None,
        forced_recommendation_title: Optional[str] = None,
        conversation_context: Optional[list[Dict[str, Any]]] = None,
        session_memory: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        started_at = time.perf_counter()
        plan = self.planner.plan(
            user_query,
            scenic_slug=scenic_slug,
            conversation_context=conversation_context,
            session_memory=session_memory,
        )
        intent = plan.intent
        context_attraction = _resolve_context_attraction(
            user_query,
            start_attraction,
            conversation_context=conversation_context,
            session_memory=session_memory,
        )

        if plan.strategy == "general_chat":
            fallback_chat_reply = _fallback_general_chat_reply(user_query)
            screened_chat_reply = None if _looks_like_non_social_task(user_query) else (
                fallback_chat_reply or detect_general_chat_reply(user_query)
            )
            if not screened_chat_reply:
                plan.intent = "FACT"
                plan.strategy = "structured_fact"
                plan.reasoning = list(getattr(plan, "reasoning", []) or []) + [
                    "General-chat plan was not confirmed by chat screener; continuing with tool execution."
                ]
                intent = plan.intent

        if plan.strategy == "general_chat":
            general_chat_reply = (
                _fallback_general_chat_reply(user_query)
                or _normalize_general_chat_reply(plan.chat_reply, "你好，我在。", max_chars=80)
                or detect_general_chat_reply(user_query)
                or "你好，我在。"
            )
            return self._finalize_response(
                started_at,
                user_query,
                "CHAT",
                "general_chat",
                general_chat_reply,
                "chat",
                SimpleNamespace(
                    strategy="general_chat",
                    question_type=None,
                    route_profile=None,
                    confidence=1.0,
                    reasoning=plan.reasoning,
                    scenic_slug=scenic_slug,
                    planner_source=plan.planner_source,
                    raw_payload=plan.raw_payload,
                ),
                recommendation=None,
            )

        if plan.strategy == "ask_clarification":
            answer = _normalize_general_chat_reply(
                plan.chat_reply,
                _build_clarification_reply(user_query, plan.question_type, plan.scenic_slug or scenic_slug),
                max_chars=96,
            )
            return self._finalize_response(
                started_at,
                user_query,
                "CHAT",
                "dialog_agent",
                answer,
                "clarification",
                plan,
                recommendation=None,
            )

        if plan.strategy == "refuse_realtime":
            answer = (
                "抱歉，这个问题需要实时运营数据或未来信息支持。"
                "我不能根据当前离线知识资料和游客行为样本编造结果。"
                "您可以改问景点事实、历史文化、推荐路线，或基于游客行为数据的统计分析。"
            )
            return self._finalize_response(
                started_at,
                user_query,
                intent,
                "query_planner",
                answer,
                "refused:realtime_required",
                plan,
                recommendation=None,
                refusal=make_refusal(
                    "realtime_required",
                    message="当前系统只支持离线事实、离线文档知识和历史行为分析。",
                    suggested_queries=[
                        "今天的客流需要接入实时系统后再问",
                        "可以先问景点事实、历史文化或游客偏好分析",
                    ],
                ),
            )

        if plan.strategy == "refuse_source_conflict":
            answer = (
                "抱歉，这个问题混用了不合适的数据源。"
                "游客行为数据只能用于统计分析，景区资料只能用于事实、历史文化和讲解内容。"
                "请拆开提问，我再分别回答。"
            )
            return self._finalize_response(
                started_at,
                user_query,
                intent,
                "query_planner",
                answer,
                "refused:source_conflict",
                plan,
                recommendation=None,
                refusal=make_refusal(
                    "source_conflict",
                    message="事实问答和行为分析需要分别求解。",
                    suggested_queries=[
                        "请单独问景点事实问题",
                        "请单独问游客行为统计问题",
                    ],
                ),
            )

        observations, agent_steps = self._run_agent_tool_loop(
            user_query=user_query,
            plan=plan,
            intent=intent,
            user_profile=user_profile,
            context_attraction=context_attraction,
            scenic_slug=scenic_slug,
            attraction_id=attraction_id,
            forced_recommendation_profile=forced_recommendation_profile,
            forced_recommendation_title=forced_recommendation_title,
        )
        final_observation = self._select_final_observation(observations)
        result = self._synthesize_tool_result(user_query, plan, observations, final_observation)
        agent_type = self._agent_type_for_tool(final_observation.tool_name)
        trace = self._build_tool_trace(
            observations,
            agent_steps,
            conversation_context=conversation_context,
            session_memory=session_memory,
            context_attraction=context_attraction,
            result=result,
        )
        result, trace, final_observation = self._review_and_repair_tool_result(
            user_query=user_query,
            plan=plan,
            observations=observations,
            agent_steps=agent_steps,
            final_observation=final_observation,
            result=result,
            trace=trace,
            user_profile=user_profile,
            context_attraction=context_attraction,
            scenic_slug=scenic_slug,
            attraction_id=attraction_id,
            forced_recommendation_profile=forced_recommendation_profile,
            forced_recommendation_title=forced_recommendation_title,
            conversation_context=conversation_context,
            session_memory=session_memory,
        )
        agent_type = self._agent_type_for_tool(final_observation.tool_name)
        return self._finalize_response(
            started_at,
            user_query,
            intent,
            agent_type,
            result["answer"],
            result.get("response_kind", "fact"),
            plan,
            recommendation=result.get("recommendation"),
            matched_attraction=result.get("matched_attraction"),
            recommendation_label=result.get("recommendation_label") or (
                extract_interest_label(user_query) if agent_type == "scenic_recommendation" else None
            ),
            evidence=result.get("evidence"),
            refusal=result.get("refusal"),
            warnings=result.get("warnings"),
            trace=trace,
        )

    def _run_agent_tool_loop(
        self,
        *,
        user_query: str,
        plan: Any,
        intent: str,
        user_profile: Optional[str],
        context_attraction: Optional[str],
        scenic_slug: Optional[str],
        attraction_id: Optional[str],
        forced_recommendation_profile: Optional[str],
        forced_recommendation_title: Optional[str],
    ) -> tuple[list[ToolObservation], list[AgentStep]]:
        observations: list[ToolObservation] = []
        agent_steps: list[AgentStep] = []
        seen_tools: set[str] = set()
        first_call = self._tool_call_from_plan(
            user_query=user_query,
            plan=plan,
            intent=intent,
            user_profile=user_profile,
            context_attraction=context_attraction,
            scenic_slug=scenic_slug,
            attraction_id=attraction_id,
            forced_recommendation_profile=forced_recommendation_profile,
            forced_recommendation_title=forced_recommendation_title,
        )
        first_step = AgentStep(
            action="call_tool",
            reason=first_call.reason or "planner_selected_initial_tool",
            source="planner",
            tool_call=first_call,
        )
        agent_steps.append(first_step)
        next_step: Optional[AgentStep] = first_step

        while next_step and next_step.action == "call_tool" and next_step.tool_call and len(observations) < 3:
            call = next_step.tool_call
            if call.name in seen_tools:
                agent_steps.append(
                    AgentStep(
                        action="ask_clarification",
                        reason=f"tool_already_called:{call.name}",
                        source="agent_policy_fallback",
                    )
                )
                break
            seen_tools.add(call.name)
            observation = self.tool_runner.run(call)
            observations.append(observation)
            candidate_calls = self._candidate_tools_after_observation(
                observation,
                user_query=user_query,
                plan=plan,
                user_profile=user_profile,
                context_attraction=context_attraction,
                scenic_slug=scenic_slug,
                attraction_id=attraction_id,
                forced_recommendation_profile=forced_recommendation_profile,
                forced_recommendation_title=forced_recommendation_title,
            )
            candidate_calls = [candidate for candidate in candidate_calls if candidate.name not in seen_tools]
            next_step = self.agent_loop.decide_next(
                user_query=user_query,
                plan=plan,
                observations=observations,
                candidate_calls=candidate_calls,
            )
            agent_steps.append(next_step)
            if next_step.action != "call_tool":
                break
        return observations, agent_steps

    def _tool_call_from_plan(
        self,
        *,
        user_query: str,
        plan: Any,
        intent: str,
        user_profile: Optional[str],
        context_attraction: Optional[str],
        scenic_slug: Optional[str],
        attraction_id: Optional[str],
        forced_recommendation_profile: Optional[str],
        forced_recommendation_title: Optional[str],
    ) -> ToolCall:
        if plan.strategy == "semantic_sql" or intent == "ANALYTICS":
            return ToolCall("behavior_sql", {"user_query": user_query}, reason="planner_selected_semantic_sql")
        if plan.strategy == "route_planner" or intent == "RECOMMEND":
            return ToolCall(
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
        tool_name = "hybrid_rag" if plan.strategy == "hybrid_rag" else "structured_fact"
        return self._fact_tool_call(
            tool_name,
            user_query=user_query,
            plan=plan,
            context_attraction=context_attraction,
            scenic_slug=scenic_slug,
            attraction_id=attraction_id,
            reason=f"planner_selected_{tool_name}",
        )

    def _fact_tool_call(
        self,
        tool_name: str,
        *,
        user_query: str,
        plan: Any,
        context_attraction: Optional[str],
        scenic_slug: Optional[str],
        attraction_id: Optional[str],
        reason: str,
    ) -> ToolCall:
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

    def _candidate_tools_after_observation(
        self,
        observation: ToolObservation,
        *,
        user_query: str,
        plan: Any,
        user_profile: Optional[str],
        context_attraction: Optional[str],
        scenic_slug: Optional[str],
        attraction_id: Optional[str],
        forced_recommendation_profile: Optional[str],
        forced_recommendation_title: Optional[str],
    ) -> list[ToolCall]:
        if not observation.insufficient:
            return []
        suggested = set(observation.suggested_next_tools or [])
        candidates: list[ToolCall] = []
        if observation.tool_name == "structured_fact":
            candidates.append(
                self._fact_tool_call(
                    "hybrid_rag",
                    user_query=user_query,
                    plan=plan,
                    context_attraction=context_attraction,
                    scenic_slug=scenic_slug,
                    attraction_id=attraction_id,
                    reason="agent_observation_suggested_hybrid_rag",
                )
            )
        if observation.tool_name == "behavior_sql" and (
            "hybrid_rag" in suggested or observation.response_kind in {"analytics:unresolved", "analytics:empty"}
        ):
            candidates.append(
                self._fact_tool_call(
                    "hybrid_rag",
                    user_query=user_query,
                    plan=plan,
                    context_attraction=context_attraction,
                    scenic_slug=scenic_slug,
                    attraction_id=attraction_id,
                    reason="agent_observation_suggested_hybrid_rag_after_sql",
                )
            )
        if observation.tool_name == "route_planner" and ("structured_fact" in suggested or observation.insufficient):
            candidates.append(
                self._fact_tool_call(
                    "structured_fact",
                    user_query=user_query,
                    plan=plan,
                    context_attraction=context_attraction,
                    scenic_slug=scenic_slug,
                    attraction_id=attraction_id,
                    reason="agent_observation_suggested_structured_fact_after_route",
                )
            )
        return candidates

    @staticmethod
    def _select_final_observation(observations: list[ToolObservation]) -> ToolObservation:
        for observation in reversed(observations):
            if observation.ok and not observation.insufficient:
                return observation
        for observation in reversed(observations):
            if observation.ok:
                return observation
        return observations[-1]

    def _synthesize_tool_result(
        self,
        user_query: str,
        plan: Any,
        observations: list[ToolObservation],
        final_observation: ToolObservation,
    ) -> Dict[str, Any]:
        result = dict(final_observation.result or {})
        result.setdefault("answer", final_observation.answer)
        result.setdefault("response_kind", final_observation.response_kind)
        result.setdefault("evidence", final_observation.evidence)
        result.setdefault("refusal", final_observation.refusal)
        result.setdefault("warnings", final_observation.warnings)
        if result.get("response_kind") == "structured_override":
            evidence_field = ""
            for item in result.get("evidence") or []:
                if isinstance(item, dict) and item.get("field"):
                    evidence_field = str(item["field"])
                    break
            result["response_kind"] = f"field:{evidence_field or plan.question_type or 'description'}"

        if final_observation.insufficient and not final_observation.refusal:
            result["answer"] = _build_clarification_reply(user_query, plan.question_type, plan.scenic_slug)
            result["response_kind"] = "clarification"
            result["refusal"] = None
            result["warnings"] = list(result.get("warnings") or []) + ["agent_tool_result_insufficient"]
            return result

        if len(observations) <= 1:
            return result

        best_answer = str(result.get("answer") or "").strip()
        supporting = [
            observation
            for observation in observations
            if observation is not final_observation
            and observation.ok
            and observation.evidence
            and not observation.insufficient
        ]
        if not best_answer or not supporting:
            return result

        synthesized = self._try_llm_synthesis(user_query, plan, final_observation, supporting)
        if synthesized:
            result["answer"] = synthesized
            result["response_kind"] = result.get("response_kind") or final_observation.response_kind
            result["warnings"] = list(result.get("warnings") or []) + ["agent_synthesized_from_tool_observations"]
        return result

    def _review_and_repair_tool_result(
        self,
        *,
        user_query: str,
        plan: Any,
        observations: list[ToolObservation],
        agent_steps: list[AgentStep],
        final_observation: ToolObservation,
        result: Dict[str, Any],
        trace: Dict[str, Any],
        user_profile: Optional[str],
        context_attraction: Optional[str],
        scenic_slug: Optional[str],
        attraction_id: Optional[str],
        forced_recommendation_profile: Optional[str],
        forced_recommendation_title: Optional[str],
        conversation_context: Optional[list[Dict[str, Any]]],
        session_memory: Optional[Dict[str, Any]],
    ) -> tuple[Dict[str, Any], Dict[str, Any], ToolObservation]:
        repair_history: list[Dict[str, Any]] = []
        max_repairs = 2

        for attempt in range(max_repairs + 1):
            agent_type = self._agent_type_for_tool(final_observation.tool_name)
            audited = self.answer_review_agent.review(
                user_query=user_query,
                result={
                    **result,
                    "warnings": list(result.get("warnings") or []),
                    "trace": trace,
                },
                agent_type=agent_type,
                plan=plan,
            )
            result["warnings"] = list(audited.get("warnings") or [])
            trace = audited.get("trace") if isinstance(audited.get("trace"), dict) else trace

            review = trace.get("answer_review") if isinstance(trace.get("answer_review"), dict) else {}
            if review and review.get("checked") is False:
                if repair_history:
                    trace["answer_review_repair"] = repair_history
                return result, trace, final_observation
            if not review or review.get("approved", True) or attempt >= max_repairs:
                if repair_history:
                    trace["answer_review_repair"] = repair_history
                return result, trace, final_observation

            action = str(review.get("repair_action") or "none")
            candidate_calls = self._repair_tool_candidates_from_review(
                action,
                final_observation=final_observation,
                user_query=user_query,
                plan=plan,
                user_profile=user_profile,
                context_attraction=context_attraction,
                scenic_slug=scenic_slug,
                attraction_id=attraction_id,
                forced_recommendation_profile=forced_recommendation_profile,
                forced_recommendation_title=forced_recommendation_title,
            )
            repair_step = self.agent_loop.decide_repair_from_review(
                user_query=user_query,
                plan=plan,
                observations=observations,
                review=review,
                candidate_calls=candidate_calls,
            )
            agent_steps.append(repair_step)
            if repair_step.action != "call_tool" or not repair_step.tool_call:
                repair_history.append(
                    {
                        "attempt": attempt + 1,
                        "action": action,
                        "status": "no_repair_tool",
                        "agent_step": repair_step.to_trace(),
                        "reasoning": review.get("reasoning"),
                    }
                )
                trace["answer_review_repair"] = repair_history
                return result, trace, final_observation

            repair_call = repair_step.tool_call
            repair_observation = self.tool_runner.run(repair_call)
            observations.append(repair_observation)
            repair_history.append(
                {
                    "attempt": attempt + 1,
                    "action": action,
                    "tool_name": repair_call.name,
                    "agent_step_source": repair_step.source,
                    "response_kind": repair_observation.response_kind,
                    "status": repair_observation.status,
                    "reasoning": review.get("reasoning"),
                }
            )

            final_observation = repair_observation
            result = self._synthesize_tool_result(user_query, plan, [repair_observation], final_observation)
            trace = self._build_tool_trace(
                observations,
                agent_steps,
                conversation_context=conversation_context,
                session_memory=session_memory,
                context_attraction=context_attraction,
                result=result,
            )

        if repair_history:
            trace["answer_review_repair"] = repair_history
        return result, trace, final_observation

    def _repair_tool_candidates_from_review(
        self,
        action: str,
        *,
        final_observation: ToolObservation,
        user_query: str,
        plan: Any,
        user_profile: Optional[str],
        context_attraction: Optional[str],
        scenic_slug: Optional[str],
        attraction_id: Optional[str],
        forced_recommendation_profile: Optional[str],
        forced_recommendation_title: Optional[str],
    ) -> list[ToolCall]:
        suggested_tool = (
            final_observation.tool_name
            if action == "retry_same_agent"
            else {
                "call_structured_fact": "structured_fact",
                "call_hybrid_rag": "hybrid_rag",
                "call_behavior_sql": "behavior_sql",
                "call_route_planner": "route_planner",
            }.get(action)
        )
        tool_names = [
            "structured_fact",
            "hybrid_rag",
            "behavior_sql",
            "route_planner",
        ]
        if suggested_tool in tool_names:
            tool_names = [suggested_tool] + [tool_name for tool_name in tool_names if tool_name != suggested_tool]

        calls: list[ToolCall] = []
        for tool_name in tool_names:
            call = self._build_repair_tool_call(
                tool_name,
                action=action,
                user_query=user_query,
                plan=plan,
                user_profile=user_profile,
                context_attraction=context_attraction,
                scenic_slug=scenic_slug,
                attraction_id=attraction_id,
                forced_recommendation_profile=forced_recommendation_profile,
                forced_recommendation_title=forced_recommendation_title,
            )
            if call:
                calls.append(call)
        return calls

    def _build_repair_tool_call(
        self,
        tool_name: str,
        *,
        action: str,
        user_query: str,
        plan: Any,
        user_profile: Optional[str],
        context_attraction: Optional[str],
        scenic_slug: Optional[str],
        attraction_id: Optional[str],
        forced_recommendation_profile: Optional[str],
        forced_recommendation_title: Optional[str],
    ) -> Optional[ToolCall]:
        if tool_name == "behavior_sql":
            return ToolCall("behavior_sql", {"user_query": user_query}, reason=f"answer_review_repair:{action}")
        if tool_name == "route_planner":
            return ToolCall(
                "route_planner",
                {
                    "user_query": user_query,
                    "start_attraction": context_attraction,
                    "user_profile": user_profile,
                    "scenic_slug": scenic_slug,
                    "forced_profile_key": forced_recommendation_profile or getattr(plan, "route_profile", None),
                    "forced_title": forced_recommendation_title,
                },
                reason=f"answer_review_repair:{action}",
            )
        if tool_name in {"structured_fact", "hybrid_rag"}:
            return self._fact_tool_call(
                tool_name,
                user_query=user_query,
                plan=plan,
                context_attraction=context_attraction,
                scenic_slug=scenic_slug,
                attraction_id=attraction_id,
                reason=f"answer_review_repair:{action}",
            )
        return None

    @staticmethod
    def _agent_type_for_tool(tool_name: str) -> str:
        return {
            "behavior_sql": "behavior_analytics",
            "route_planner": "scenic_recommendation",
            "structured_fact": "scenic_fact",
            "hybrid_rag": "scenic_fact",
        }.get(tool_name, "dialog_agent")

    def _build_tool_trace(
        self,
        observations: list[ToolObservation],
        agent_steps: list[AgentStep],
        *,
        conversation_context: Optional[list[Dict[str, Any]]],
        session_memory: Optional[Dict[str, Any]],
        context_attraction: Optional[str],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        final_trace = dict(result.get("trace") or {})
        trace: Dict[str, Any] = {
            "conversation": {
                "used_context": bool(conversation_context or session_memory),
                "context_attraction": context_attraction,
            },
            "tools": {
                "available": [spec["name"] for spec in ToolRunner.specs()],
                "calls": [observation.to_trace() for observation in observations],
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
        trace.update(final_trace)
        return trace

    def _try_llm_synthesis(
        self,
        user_query: str,
        plan: Any,
        final_observation: ToolObservation,
        supporting: list[ToolObservation],
    ) -> Optional[str]:
        if not supporting:
            return None
        snippets = []
        for observation in [final_observation] + supporting[:2]:
            snippets.append(
                {
                    "tool": observation.tool_name,
                    "response_kind": observation.response_kind,
                    "answer": observation.answer[:600],
                    "evidence_count": len(observation.evidence or []),
                }
            )
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
            answer = generate_chat_completion(
                prompt,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=360,
                return_error_text=False,
            )
        except Exception:
            return None
        cleaned = str(answer or "").strip().strip("\"'")
        if not cleaned or cleaned.startswith("Error"):
            return None
        return cleaned

    @staticmethod
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

    def _finalize_response(
        self,
        started_at: float,
        query: str,
        intent: str,
        agent_type: str,
        answer: str,
        response_kind: str,
        plan: Any,
        *,
        recommendation: Optional[Dict[str, Any]],
        matched_attraction: Optional[str] = None,
        recommendation_label: Optional[str] = None,
        evidence: Optional[Any] = None,
        refusal: Optional[Dict[str, Any]] = None,
        warnings: Optional[Any] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        trace = trace or {}
        if not isinstance(trace.get("answer_review"), dict):
            reviewed = self.answer_review_agent.review(
                user_query=query,
                result={
                    "answer": answer,
                    "response_kind": response_kind,
                    "recommendation": recommendation,
                    "evidence": evidence or [],
                    "refusal": refusal,
                    "warnings": list(warnings or []),
                    "trace": trace,
                },
                agent_type=agent_type,
                plan=plan,
            )
            warnings = list(reviewed.get("warnings") or [])
            trace = reviewed.get("trace") if isinstance(reviewed.get("trace"), dict) else trace
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        payload = {
            "query": query,
            "intent": intent,
            "agent_type": agent_type,
            "answer": answer,
            "matched_attraction": matched_attraction,
            "recommendation_label": recommendation_label,
            "response_kind": response_kind,
            "recommendation": recommendation,
            "plan": self._plan_payload(plan),
            "evidence": evidence or [],
            "refusal": refusal,
            "warnings": list(warnings or []),
            "observability": {
                "timestamp": utc_timestamp(),
                "latency_ms": latency_ms,
                "evidence_count": len(evidence or []),
                "fallback_used": bool((trace or {}).get("fallback_used")),
                "refusal_reason": (refusal or {}).get("reason"),
                "strategy": plan.strategy,
                "trace": trace or {},
            },
        }
        self._record_runtime_trace(payload)
        return payload

    @staticmethod
    def _record_runtime_trace(payload: Dict[str, Any]) -> None:
        observability = payload.get("observability") or {}
        compact = {
            "timestamp": observability.get("timestamp"),
            "query": str(payload.get("query") or "")[:160],
            "intent": payload.get("intent"),
            "agent_type": payload.get("agent_type"),
            "response_kind": payload.get("response_kind"),
            "strategy": (payload.get("plan") or {}).get("strategy"),
            "latency_ms": observability.get("latency_ms"),
            "evidence_count": observability.get("evidence_count"),
            "fallback_used": observability.get("fallback_used"),
            "refusal_reason": observability.get("refusal_reason"),
            "warnings": list(payload.get("warnings") or [])[:5],
        }
        merge_runtime_status({"last_query_trace": compact})
