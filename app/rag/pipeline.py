import json
import re
import time
from types import SimpleNamespace
from typing import Any, Dict, Optional

from app.core.runtime import merge_runtime_status, utc_timestamp
from app.rag.fact_agent import ScenicFactAgent, extract_interest_label
from app.rag.llm_client import generate_chat_completion
from app.rag.planner import QueryPlanner
from app.rag.recommendation_agent import ScenicRecommendationAgent
from app.rag.response_contract import make_refusal
from app.rag.sql_agent import TouristAnalyticsAgent


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
        return "\u6211\u662f\u666f\u533a\u5bfc\u89c8\u52a9\u624b\u3002"
    if re.fullmatch(r"(好的|好哦|收到|明白了|嗯嗯|行|ok|okay)[!,.?~]*", query, re.IGNORECASE):
        return "\u597d\u7684\u3002"
    if any(pattern.fullmatch(str(user_query or "").strip()) for pattern in GENERAL_CHAT_EXACT_PATTERNS):
        return "\u4f60\u8bf4\uff0c\u6211\u5728\u542c\u3002"
    return None


def _normalize_general_chat_reply(reply: str, fallback: str) -> str:
    normalized = re.sub(r"\s+", " ", str(reply or "")).strip().strip("\"'")
    if not normalized:
        return fallback
    parts = [part.strip() for part in re.split(r"(?<=[。！？!?])", normalized) if part.strip()]
    short_reply = parts[0] if parts else normalized
    if len(short_reply) > 24:
        short_reply = short_reply[:24].rstrip("，。！？!? ")
    return short_reply or fallback


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

    def process_query(
        self,
        user_query: str,
        user_profile: Optional[str] = None,
        start_attraction: Optional[str] = None,
        scenic_slug: Optional[str] = None,
        attraction_id: Optional[str] = None,
        forced_recommendation_profile: Optional[str] = None,
        forced_recommendation_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        started_at = time.perf_counter()
        general_chat_reply = detect_general_chat_reply(user_query)
        if general_chat_reply:
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
                    reasoning="llm_or_heuristic_general_chat",
                    scenic_slug=scenic_slug,
                ),
                recommendation=None,
            )

        plan = self.planner.plan(user_query, scenic_slug=scenic_slug)
        intent = plan.intent

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

        if plan.strategy == "semantic_sql" or intent == "ANALYTICS":
            result = self.analytics_agent.query_with_trace(user_query)
            return self._finalize_response(
                started_at,
                user_query,
                intent,
                "behavior_analytics",
                result["answer"],
                result.get("response_kind", "analytics"),
                plan,
                recommendation=None,
                evidence=result.get("evidence"),
                refusal=result.get("refusal"),
                warnings=result.get("warnings"),
                trace={
                    "analytics": {
                        "semantic_plan": result.get("semantic_plan"),
                        "sql": result.get("sql"),
                        "rows_preview": result.get("rows_preview"),
                    },
                    **(result.get("trace") or {}),
                },
            )

        if plan.strategy == "route_planner" or intent == "RECOMMEND":
            result = self.recommendation_agent.answer(
                user_query,
                start_attraction=start_attraction,
                user_profile=user_profile,
                scenic_slug=scenic_slug,
                forced_profile_key=forced_recommendation_profile,
                forced_title=forced_recommendation_title,
            )
            return self._finalize_response(
                started_at,
                user_query,
                intent,
                "scenic_recommendation",
                result["answer"],
                result.get("response_kind", "recommendation"),
                plan,
                recommendation=result.get("recommendation"),
                matched_attraction=result.get("matched_attraction"),
                recommendation_label=result.get("recommendation_label") or extract_interest_label(user_query),
                evidence=result.get("evidence"),
                trace=result.get("trace"),
            )

        result = self.fact_agent.answer(
            user_query,
            scenic_slug=plan.scenic_slug or scenic_slug,
            attraction_id=attraction_id,
            attraction_name=start_attraction,
            retrieval_mode="hybrid" if plan.strategy == "hybrid_rag" else "structured_only",
        )
        return self._finalize_response(
            started_at,
            user_query,
            intent,
            "scenic_fact",
            result["answer"],
            result.get("response_kind", "fact"),
            plan,
            recommendation=None,
            matched_attraction=result.get("matched_attraction"),
            evidence=result.get("evidence"),
            refusal=result.get("refusal"),
            trace=result.get("trace"),
        )

    @staticmethod
    def _plan_payload(plan: Any) -> Dict[str, Any]:
        return {
            "strategy": plan.strategy,
            "question_type": plan.question_type,
            "route_profile": plan.route_profile,
            "confidence": plan.confidence,
            "reasoning": plan.reasoning,
            "scenic_slug": plan.scenic_slug,
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
