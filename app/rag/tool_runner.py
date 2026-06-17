from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.rag.fact_agent import ScenicFactAgent
from app.rag.recommendation_agent import ScenicRecommendationAgent
from app.rag.sql_agent import TouristAnalyticsAgent


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]
    reason: str = ""
    call_id: str = field(default_factory=lambda: f"tool_{uuid.uuid4().hex[:12]}")


@dataclass
class ToolObservation:
    call_id: str
    tool_name: str
    ok: bool
    answer: str = ""
    response_kind: str = ""
    result: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    refusal: Optional[Dict[str, Any]] = None
    warnings: List[Any] = field(default_factory=list)
    trace: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    latency_ms: float = 0.0
    insufficient: bool = False
    status: str = "ok"
    confidence: float = 0.8
    missing_slots: List[str] = field(default_factory=list)
    suggested_next_tools: List[str] = field(default_factory=list)

    def to_trace(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "ok": self.ok,
            "status": self.status,
            "confidence": self.confidence,
            "response_kind": self.response_kind,
            "evidence_count": len(self.evidence or []),
            "refusal_reason": (self.refusal or {}).get("reason"),
            "warnings": list(self.warnings or [])[:5],
            "missing_slots": list(self.missing_slots or [])[:5],
            "suggested_next_tools": list(self.suggested_next_tools or [])[:5],
            "latency_ms": self.latency_ms,
            "insufficient": self.insufficient,
            "error": self.error,
        }


class ToolRunner:
    """Standard runtime boundary for scenic-guide tools."""

    SPECS: Dict[str, ToolSpec] = {
        "structured_fact": ToolSpec(
            name="structured_fact",
            description="Answer scenic factual questions from structured attraction records.",
            input_schema={
                "type": "object",
                "properties": {
                    "user_query": {"type": "string"},
                    "scenic_slug": {"type": ["string", "null"]},
                    "attraction_id": {"type": ["string", "null"]},
                    "attraction_name": {"type": ["string", "null"]},
                    "planned_question_type": {"type": ["string", "null"]},
                },
                "required": ["user_query"],
            },
        ),
        "hybrid_rag": ToolSpec(
            name="hybrid_rag",
            description="Answer broad scenic factual questions with structured facts plus document retrieval.",
            input_schema={
                "type": "object",
                "properties": {
                    "user_query": {"type": "string"},
                    "scenic_slug": {"type": ["string", "null"]},
                    "attraction_id": {"type": ["string", "null"]},
                    "attraction_name": {"type": ["string", "null"]},
                    "planned_question_type": {"type": ["string", "null"]},
                },
                "required": ["user_query"],
            },
        ),
        "behavior_sql": ToolSpec(
            name="behavior_sql",
            description="Analyze historical tourist behavior samples through SQL.",
            input_schema={
                "type": "object",
                "properties": {"user_query": {"type": "string"}},
                "required": ["user_query"],
            },
        ),
        "route_planner": ToolSpec(
            name="route_planner",
            description="Build scenic route recommendations from profiles, facts, and behavior hints.",
            input_schema={
                "type": "object",
                "properties": {
                    "user_query": {"type": "string"},
                    "start_attraction": {"type": ["string", "null"]},
                    "user_profile": {"type": ["string", "null"]},
                    "scenic_slug": {"type": ["string", "null"]},
                    "forced_profile_key": {"type": ["string", "null"]},
                    "forced_title": {"type": ["string", "null"]},
                },
                "required": ["user_query"],
            },
        ),
    }

    def __init__(
        self,
        *,
        fact_agent: ScenicFactAgent,
        analytics_agent: TouristAnalyticsAgent,
        recommendation_agent: ScenicRecommendationAgent,
    ) -> None:
        self.fact_agent = fact_agent
        self.analytics_agent = analytics_agent
        self.recommendation_agent = recommendation_agent
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "structured_fact": self._run_structured_fact,
            "hybrid_rag": self._run_hybrid_rag,
            "behavior_sql": self._run_behavior_sql,
            "route_planner": self._run_route_planner,
        }

    @classmethod
    def specs(cls) -> List[Dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
            }
            for spec in cls.SPECS.values()
        ]

    def run(self, call: ToolCall) -> ToolObservation:
        started_at = time.perf_counter()
        handler = self._handlers.get(call.name)
        if not handler:
            return ToolObservation(
                call_id=call.call_id,
                tool_name=call.name,
                ok=False,
                response_kind="tool:error",
                error=f"unknown_tool:{call.name}",
                latency_ms=self._elapsed_ms(started_at),
                insufficient=True,
                status="error",
                confidence=0.0,
            )

        try:
            result = handler(call.arguments)
        except Exception as exc:  # pragma: no cover - defensive runtime boundary
            return ToolObservation(
                call_id=call.call_id,
                tool_name=call.name,
                ok=False,
                response_kind="tool:error",
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=self._elapsed_ms(started_at),
                insufficient=True,
                status="error",
                confidence=0.0,
            )

        response_kind = str(result.get("response_kind") or "")
        evidence = list(result.get("evidence") or [])
        refusal = result.get("refusal") if isinstance(result.get("refusal"), dict) else None
        warnings = list(result.get("warnings") or [])
        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
        insufficient = self._is_insufficient(response_kind, evidence, refusal, warnings, result)
        status = self._status(response_kind, refusal, insufficient)
        confidence = self._confidence(response_kind, evidence, refusal, insufficient)
        missing_slots = self._missing_slots(response_kind, refusal)
        suggested_next_tools = self._suggested_next_tools(call.name, response_kind, refusal, warnings, result)
        ok = not response_kind.startswith("tool:error")
        return ToolObservation(
            call_id=call.call_id,
            tool_name=call.name,
            ok=ok,
            answer=str(result.get("answer") or ""),
            response_kind=response_kind,
            result=result,
            evidence=evidence,
            refusal=refusal,
            warnings=warnings,
            trace=trace or {},
            latency_ms=self._elapsed_ms(started_at),
            insufficient=insufficient,
            status=status,
            confidence=confidence,
            missing_slots=missing_slots,
            suggested_next_tools=suggested_next_tools,
        )

    def _run_structured_fact(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.fact_agent.answer(
            str(args.get("user_query") or ""),
            scenic_slug=args.get("scenic_slug"),
            attraction_id=args.get("attraction_id"),
            attraction_name=args.get("attraction_name"),
            retrieval_mode="structured_only",
            planned_question_type=args.get("planned_question_type"),
        )

    def _run_hybrid_rag(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.fact_agent.answer(
            str(args.get("user_query") or ""),
            scenic_slug=args.get("scenic_slug"),
            attraction_id=args.get("attraction_id"),
            attraction_name=args.get("attraction_name"),
            retrieval_mode="hybrid",
            planned_question_type=args.get("planned_question_type"),
        )

    def _run_behavior_sql(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.analytics_agent.query_with_trace(str(args.get("user_query") or ""))

    def _run_route_planner(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.recommendation_agent.answer(
            str(args.get("user_query") or ""),
            start_attraction=args.get("start_attraction"),
            user_profile=args.get("user_profile"),
            scenic_slug=args.get("scenic_slug"),
            forced_profile_key=args.get("forced_profile_key"),
            forced_title=args.get("forced_title"),
        )

    @staticmethod
    def _is_insufficient(
        response_kind: str,
        evidence: List[Dict[str, Any]],
        refusal: Optional[Dict[str, Any]],
        warnings: List[Any],
        result: Dict[str, Any],
    ) -> bool:
        refusal_reason = str((refusal or {}).get("reason") or "")
        if refusal_reason in {"source_conflict", "realtime_required", "unsupported_fact_request"}:
            return False
        if response_kind in {
            "refused",
            "refused:no_relevant_docs",
            "refused:low_confidence",
            "refused:kb_unavailable",
            "analytics:unresolved",
            "analytics:empty",
            "analytics:error",
        }:
            return True
        if refusal_reason == "insufficient_fact_evidence":
            return True
        if any(str(item) == "semantic_parse_failed" for item in warnings):
            return True
        if response_kind == "recommendation" and not (result.get("recommendation") or {}).get("route_items"):
            return True
        return False

    @staticmethod
    def _status(response_kind: str, refusal: Optional[Dict[str, Any]], insufficient: bool) -> str:
        if response_kind.startswith("tool:error") or response_kind.endswith(":error"):
            return "error"
        refusal_reason = str((refusal or {}).get("reason") or "")
        if refusal_reason in {"source_conflict", "realtime_required", "unsupported_fact_request"}:
            return "boundary_refusal"
        if insufficient:
            return "insufficient"
        return "ok"

    @staticmethod
    def _confidence(
        response_kind: str,
        evidence: List[Dict[str, Any]],
        refusal: Optional[Dict[str, Any]],
        insufficient: bool,
    ) -> float:
        if refusal:
            return 0.95 if not insufficient else 0.35
        if insufficient:
            return 0.25
        if response_kind in {"rag_general", "rag_answer", "rag_fallback"}:
            return 0.78 if evidence else 0.55
        if evidence:
            return 0.9
        return 0.72

    @staticmethod
    def _missing_slots(response_kind: str, refusal: Optional[Dict[str, Any]]) -> List[str]:
        reason = str((refusal or {}).get("reason") or "")
        if reason == "insufficient_fact_evidence":
            return ["specific_scenic_or_attraction"]
        if response_kind in {"analytics:unresolved", "analytics:empty"}:
            return ["analysis_metric_or_filter"]
        if response_kind == "recommendation":
            return []
        return []

    @staticmethod
    def _suggested_next_tools(
        tool_name: str,
        response_kind: str,
        refusal: Optional[Dict[str, Any]],
        warnings: List[Any],
        result: Dict[str, Any],
    ) -> List[str]:
        reason = str((refusal or {}).get("reason") or "")
        if reason in {"source_conflict", "realtime_required", "unsupported_fact_request"}:
            return []
        if tool_name == "structured_fact" and (response_kind == "refused" or reason == "insufficient_fact_evidence"):
            return ["hybrid_rag"]
        if tool_name == "behavior_sql" and (
            response_kind in {"analytics:unresolved", "analytics:empty"} or "semantic_parse_failed" in warnings
        ):
            return ["hybrid_rag"]
        if tool_name == "route_planner" and not (result.get("recommendation") or {}).get("route_items"):
            return ["structured_fact"]
        return []

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        return round((time.perf_counter() - started_at) * 1000, 2)
