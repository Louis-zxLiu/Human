import time
from typing import Any, Dict, Optional

from app.core.runtime import merge_runtime_status, utc_timestamp
from app.rag.fact_agent import ScenicFactAgent, extract_interest_label
from app.rag.planner import QueryPlanner
from app.rag.recommendation_agent import ScenicRecommendationAgent
from app.rag.response_contract import make_refusal
from app.rag.sql_agent import TouristAnalyticsAgent


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
    ) -> Dict[str, Any]:
        started_at = time.perf_counter()
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
