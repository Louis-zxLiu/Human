import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.rag.agent_loop import AgentLoopController
from app.rag.pipeline import ScenicRAGPipeline
from app.rag.tool_runner import ToolCall, ToolObservation, ToolRunner


class FakeFactAgent:
    def answer(self, user_query, **kwargs):
        mode = kwargs.get("retrieval_mode")
        if mode == "structured_only":
            return {
                "answer": "need more evidence",
                "response_kind": "refused",
                "matched_attraction": None,
                "evidence": [],
                "refusal": {"reason": "insufficient_fact_evidence"},
                "trace": {"mode": mode},
            }
        return {
            "answer": "hybrid answer",
            "response_kind": "rag_general",
            "matched_attraction": "灵山大佛",
            "evidence": [{"source": "vector_doc", "snippet": "hybrid"}],
            "refusal": None,
            "trace": {"mode": mode},
        }


class FakeAnalyticsAgent:
    def query_with_trace(self, user_query):
        return {
            "answer": "analytics answer",
            "response_kind": "analytics",
            "semantic_plan": {"metric_key": "record_count"},
            "sql": "select count(*) from tourist_behavior",
            "rows_preview": [{"count": 1}],
            "evidence": [{"source": "behavior_sql", "snippet": "analytics"}],
            "warnings": [],
            "refusal": None,
            "trace": {"fallback_used": False},
        }


class FakeRecommendationAgent:
    def answer(self, user_query, **kwargs):
        return {
            "answer": "route answer",
            "response_kind": "recommendation",
            "matched_attraction": "灵山大佛",
            "recommendation_label": "历史文化",
            "recommendation": {"route_items": [{"name": "灵山大佛"}], "profile_key": "history"},
            "evidence": [{"source": "structured_fact_db", "snippet": "route"}],
            "trace": {"profile_key": "history"},
        }


class RepairFactAgent:
    def answer(self, user_query, **kwargs):
        mode = kwargs.get("retrieval_mode")
        if mode == "structured_only":
            return {
                "answer": "bad structured answer",
                "response_kind": "field:description",
                "matched_attraction": "灵山大佛",
                "evidence": [{"source": "structured_fact_db", "snippet": "bad"}],
                "refusal": None,
                "trace": {"mode": mode},
            }
        return {
            "answer": "hybrid repaired answer",
            "response_kind": "rag_general",
            "matched_attraction": "灵山大佛",
            "evidence": [{"source": "vector_doc", "snippet": "repaired"}],
            "refusal": None,
            "trace": {"mode": mode},
        }


class ToolRunnerAgentLoopTests(unittest.TestCase):
    def test_tool_runner_wraps_existing_agents_as_observations(self):
        runner = ToolRunner(
            fact_agent=FakeFactAgent(),
            analytics_agent=FakeAnalyticsAgent(),
            recommendation_agent=FakeRecommendationAgent(),
        )

        observation = runner.run(ToolCall("behavior_sql", {"user_query": "count"}))

        self.assertTrue(observation.ok)
        self.assertFalse(observation.insufficient)
        self.assertEqual(observation.tool_name, "behavior_sql")
        self.assertEqual(observation.response_kind, "analytics")
        self.assertEqual(observation.result["sql"], "select count(*) from tourist_behavior")

    def test_pipeline_self_corrects_from_structured_fact_to_hybrid_rag(self):
        pipeline = ScenicRAGPipeline()
        pipeline.tool_runner = ToolRunner(
            fact_agent=FakeFactAgent(),
            analytics_agent=FakeAnalyticsAgent(),
            recommendation_agent=FakeRecommendationAgent(),
        )
        pipeline.planner.plan = lambda *args, **kwargs: SimpleNamespace(
            intent="FACT",
            strategy="structured_fact",
            scenic_slug="lingshan-shengjing",
            question_type="description",
            route_profile="general",
            confidence=0.9,
            reasoning=["test"],
            planner_source="test",
            raw_payload={},
        )

        result = pipeline.process_query("讲讲灵山胜境概况")

        self.assertEqual(result["answer"], "hybrid answer")
        self.assertEqual(result["response_kind"], "rag_general")
        self.assertEqual(result["matched_attraction"], "灵山大佛")
        trace = result["observability"]["trace"]["tools"]
        self.assertEqual([call["tool_name"] for call in trace["calls"]], ["structured_fact", "hybrid_rag"])
        self.assertEqual(trace["self_corrections"], 1)
        loop = result["observability"]["trace"]["agent_loop"]
        self.assertEqual(loop["steps"][0]["source"], "planner")
        self.assertEqual(loop["steps"][1]["action"], "call_tool")
        self.assertEqual(loop["steps"][-1]["action"], "final_answer")

    def test_answer_review_failure_reinvokes_child_agent(self):
        pipeline = ScenicRAGPipeline()
        pipeline.tool_runner = ToolRunner(
            fact_agent=RepairFactAgent(),
            analytics_agent=FakeAnalyticsAgent(),
            recommendation_agent=FakeRecommendationAgent(),
        )
        pipeline.planner.plan = lambda *args, **kwargs: SimpleNamespace(
            intent="FACT",
            strategy="structured_fact",
            scenic_slug="lingshan-shengjing",
            question_type="description",
            route_profile="general",
            confidence=0.9,
            reasoning=["test"],
            planner_source="test",
            raw_payload={},
        )

        review_calls = []

        def fake_review(*, user_query, result, agent_type, plan=None):
            review_calls.append(result["answer"])
            reviewed = dict(result)
            trace = dict(reviewed.get("trace") or {})
            if result["answer"] == "bad structured answer":
                trace["answer_review"] = {
                    "checked": True,
                    "reviewer": "llm",
                    "approved": False,
                    "issues": ["overclaim"],
                    "repair_action": "call_hybrid_rag",
                    "agent_type": agent_type,
                    "risk_level": "major",
                    "reasoning": "Need document evidence.",
                }
                reviewed["warnings"] = list(reviewed.get("warnings") or []) + ["answer_review:not_approved"]
            else:
                trace["answer_review"] = {
                    "checked": True,
                    "reviewer": "llm",
                    "approved": True,
                    "issues": [],
                    "repair_action": "none",
                    "agent_type": agent_type,
                    "risk_level": "ok",
                    "reasoning": "OK.",
                }
            reviewed["trace"] = trace
            return reviewed

        pipeline.answer_review_agent.review = fake_review

        with patch("app.rag.agent_loop.llm_is_configured", return_value=False):
            result = pipeline.process_query("讲讲灵山胜境概况")

        self.assertEqual(result["answer"], "hybrid repaired answer")
        self.assertEqual(result["response_kind"], "rag_general")
        self.assertEqual(review_calls, ["bad structured answer", "hybrid repaired answer"])
        trace = result["observability"]["trace"]["tools"]
        self.assertEqual([call["tool_name"] for call in trace["calls"]], ["structured_fact", "hybrid_rag"])
        self.assertEqual(result["observability"]["trace"]["answer_review_repair"][0]["action"], "call_hybrid_rag")
        self.assertEqual(
            result["observability"]["trace"]["answer_review_repair"][0]["agent_step_source"],
            "main_agent_policy_fallback",
        )
        self.assertEqual(
            result["observability"]["trace"]["agent_loop"]["steps"][2]["source"],
            "main_agent_policy_fallback",
        )

    def test_main_agent_semantically_selects_repair_child_agent(self):
        pipeline = ScenicRAGPipeline()
        pipeline.tool_runner = ToolRunner(
            fact_agent=RepairFactAgent(),
            analytics_agent=FakeAnalyticsAgent(),
            recommendation_agent=FakeRecommendationAgent(),
        )
        pipeline.planner.plan = lambda *args, **kwargs: SimpleNamespace(
            intent="FACT",
            strategy="structured_fact",
            scenic_slug="lingshan-shengjing",
            question_type="description",
            route_profile="general",
            confidence=0.9,
            reasoning=["test"],
            planner_source="test",
            raw_payload={},
        )

        def fake_review(*, user_query, result, agent_type, plan=None):
            reviewed = dict(result)
            trace = dict(reviewed.get("trace") or {})
            if result["answer"] == "bad structured answer":
                trace["answer_review"] = {
                    "checked": True,
                    "reviewer": "llm",
                    "approved": False,
                    "issues": ["overclaim"],
                    "repair_action": "call_structured_fact",
                    "agent_type": agent_type,
                    "risk_level": "major",
                    "reasoning": "Need broader document evidence, not a rewritten answer.",
                }
                reviewed["warnings"] = list(reviewed.get("warnings") or []) + ["answer_review:not_approved"]
            else:
                trace["answer_review"] = {
                    "checked": True,
                    "reviewer": "llm",
                    "approved": True,
                    "issues": [],
                    "repair_action": "none",
                    "agent_type": agent_type,
                    "risk_level": "ok",
                    "reasoning": "OK.",
                }
            reviewed["trace"] = trace
            return reviewed

        pipeline.answer_review_agent.review = fake_review

        with patch("app.rag.agent_loop.llm_is_configured", return_value=True), patch(
            "app.rag.agent_loop.generate_chat_completion",
            return_value='{"action":"call_tool","tool_name":"hybrid_rag","reason":"Need doc evidence."}',
        ):
            result = pipeline.process_query("讲讲灵山胜境概况")

        self.assertEqual(result["answer"], "hybrid repaired answer")
        repair = result["observability"]["trace"]["answer_review_repair"][0]
        self.assertEqual(repair["action"], "call_structured_fact")
        self.assertEqual(repair["tool_name"], "hybrid_rag")
        self.assertEqual(repair["agent_step_source"], "main_agent_llm")
        self.assertEqual(
            result["observability"]["trace"]["agent_loop"]["steps"][2]["source"],
            "main_agent_llm",
        )

    def test_agent_loop_can_use_llm_observation_decision_to_ask_clarification(self):
        controller = AgentLoopController()
        observation = ToolObservation(
            call_id="tool_test",
            tool_name="structured_fact",
            ok=True,
            response_kind="refused",
            refusal={"reason": "insufficient_fact_evidence"},
            insufficient=True,
            status="insufficient",
            missing_slots=["specific_scenic_or_attraction"],
            suggested_next_tools=["hybrid_rag"],
        )

        with patch("app.rag.agent_loop.llm_is_configured", return_value=True), patch(
            "app.rag.agent_loop.generate_chat_completion",
            return_value='{"action":"ask_clarification","tool_name":"","reason":"missing attraction"}',
        ):
            step = controller.decide_next(
                user_query="介绍一下景点",
                plan=SimpleNamespace(strategy="structured_fact", question_type="description"),
                observations=[observation],
                candidate_calls=[ToolCall("hybrid_rag", {"user_query": "介绍一下景点"})],
            )

        self.assertEqual(step.action, "ask_clarification")
        self.assertEqual(step.source, "agent_llm")
        self.assertEqual(step.observation_summary["missing_slots"], ["specific_scenic_or_attraction"])


if __name__ == "__main__":
    unittest.main()
