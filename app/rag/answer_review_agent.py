from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from app.rag.llm_client import generate_chat_completion, llm_is_configured


class AnswerReviewAgent:
    """Final answer reviewer for tool outputs before user-facing response."""

    FIELD_LEAK_PATTERN = re.compile(
        r"\b(?:avg_[a-z_]+|[a-z]+_cost|record_count|low_satisfaction_count|high_satisfaction_count)\b"
    )
    LONG_FLOAT_PATTERN = re.compile(r"\d+\.\d{4,}")

    def review(
        self,
        *,
        user_query: str,
        result: Dict[str, Any],
        agent_type: str,
        plan: Any = None,
    ) -> Dict[str, Any]:
        audited = dict(result or {})
        answer = str(audited.get("answer") or "")
        issues = self._detect_issues(answer, audited)
        trace = dict(audited.get("trace") or {})
        warnings = list(audited.get("warnings") or [])

        if not llm_is_configured():
            if "answer_review:llm_unavailable" not in warnings:
                warnings.append("answer_review:llm_unavailable")
            if "answer_review:not_approved" not in warnings:
                warnings.append("answer_review:not_approved")
            trace["answer_review"] = {
                "checked": False,
                "reviewer": "llm",
                "approved": False,
                "issues": issues,
                "repair_action": "retry_same_agent",
                "agent_type": agent_type,
                "reason": "llm_unavailable",
            }
            audited["trace"] = trace
            audited["warnings"] = warnings
            return audited

        payload = self._call_llm_reviewer(
            user_query=user_query,
            result=audited,
            agent_type=agent_type,
            plan=plan,
            detected_issues=issues,
        )
        if not payload:
            if "answer_review:llm_failed" not in warnings:
                warnings.append("answer_review:llm_failed")
            if "answer_review:not_approved" not in warnings:
                warnings.append("answer_review:not_approved")
            trace["answer_review"] = {
                "checked": False,
                "reviewer": "llm",
                "approved": False,
                "issues": issues,
                "repair_action": "retry_same_agent",
                "agent_type": agent_type,
                "reason": "invalid_reviewer_payload",
            }
            audited["trace"] = trace
            audited["warnings"] = warnings
            return audited

        review_issues = [str(item) for item in payload.get("issues") or [] if str(item).strip()]
        for issue in review_issues or issues:
            marker = f"answer_review:{issue}"
            if marker not in warnings:
                warnings.append(marker)

        approved = bool(payload.get("approved"))
        repair_action = self._normalize_repair_action(payload.get("repair_action"))
        if not approved and "answer_review:not_approved" not in warnings:
            warnings.append("answer_review:not_approved")

        trace["answer_review"] = {
            "checked": True,
            "reviewer": "llm",
            "approved": approved,
            "issues": review_issues or issues,
            "repair_action": repair_action,
            "agent_type": agent_type,
            "risk_level": str(payload.get("risk_level") or ""),
            "reasoning": str(payload.get("reasoning") or "")[:240],
        }
        audited["trace"] = trace
        audited["warnings"] = warnings
        return audited

    def _call_llm_reviewer(
        self,
        *,
        user_query: str,
        result: Dict[str, Any],
        agent_type: str,
        plan: Any,
        detected_issues: list[str],
    ) -> Optional[Dict[str, Any]]:
        semantic_plan = result.get("semantic_plan")
        rows_preview = result.get("rows_preview")
        if not semantic_plan:
            trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
            analytics_trace = trace.get("analytics") if isinstance(trace.get("analytics"), dict) else {}
            semantic_plan = analytics_trace.get("semantic_plan")
            rows_preview = rows_preview or analytics_trace.get("rows_preview")

        review_context = {
            "user_query": user_query,
            "agent_type": agent_type,
            "response_kind": result.get("response_kind"),
            "answer": result.get("answer"),
            "semantic_plan": semantic_plan,
            "rows_preview": rows_preview,
            "evidence": result.get("evidence"),
            "refusal": result.get("refusal"),
            "warnings": result.get("warnings"),
            "deterministic_issue_signals": detected_issues,
            "main_plan": self._compact_plan(plan),
        }
        system_prompt = (
            "You are the final LLM review agent for a scenic-guide multi-agent system. "
            "You must audit every final answer before it is shown to the user. "
            "Return strict JSON only."
        )
        prompt = (
            "Review the candidate answer using only the supplied context. Do not add new facts.\n"
            "You are an auditor only: do not rewrite the answer and do not provide replacement answer text.\n"
            "If the answer is already safe and natural, return approved=true and repair_action=none.\n"
            "If it leaks machine fields, has unformatted numbers, misses units, mixes data sources, "
            "overclaims evidence, or is unnatural for a visitor, return approved=false and choose a repair action for the main agent.\n"
            "For analytics answers: never expose SQL column names such as avg_cost or avg_total_cost; "
            "round decimals to at most 2 places; include natural Chinese labels and units; keep the data-source prefix. "
            "A value like 692.89元 is already formatted and must not be flagged as an unformatted number.\n"
            "For refusals: preserve the refusal boundary and do not answer the refused question.\n"
            "For chat: keep it concise and natural.\n\n"
            "Return JSON with this schema:\n"
            "{\n"
            '  "approved": true/false,\n'
            '  "issues": ["field_name_leak|unformatted_number|missing_unit|source_conflict|overclaim|unnatural|other"],\n'
            '  "risk_level": "ok|minor|major",\n'
            '  "repair_action": "none|retry_same_agent|call_structured_fact|call_hybrid_rag|call_behavior_sql|call_route_planner|ask_clarification|refuse",\n'
            '  "reasoning": "short Chinese reason"\n'
            "}\n\n"
            f"Context: {json.dumps(review_context, ensure_ascii=False, default=str)}\n"
            "JSON only."
        )
        raw = generate_chat_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.0,
            max_tokens=520,
            return_error_text=False,
        )
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
        text = str(raw or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()
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

    @staticmethod
    def _compact_plan(plan: Any) -> Dict[str, Any]:
        if not plan:
            return {}
        return {
            "strategy": getattr(plan, "strategy", None),
            "question_type": getattr(plan, "question_type", None),
            "route_profile": getattr(plan, "route_profile", None),
            "planner_source": getattr(plan, "planner_source", None),
        }

    @staticmethod
    def _normalize_repair_action(value: Any) -> str:
        action = str(value or "none").strip()
        allowed = {
            "none",
            "retry_same_agent",
            "call_structured_fact",
            "call_hybrid_rag",
            "call_behavior_sql",
            "call_route_planner",
            "ask_clarification",
            "refuse",
        }
        return action if action in allowed else "none"

    def _detect_issues(self, answer: str, result: Dict[str, Any]) -> list[str]:
        issues: list[str] = []
        if self.FIELD_LEAK_PATTERN.search(answer):
            issues.append("field_name_leak")
        if self.LONG_FLOAT_PATTERN.search(answer):
            issues.append("unformatted_number")
        if str(result.get("response_kind") or "") == "analytics:fallback":
            issues.append("fallback_answer")
        return issues
