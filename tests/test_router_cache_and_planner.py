import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.rag.planner import QueryPlanner
from app.rag.router_cache import RouterPlanCache


class RouterCacheAndPlannerTests(unittest.TestCase):
    def test_router_cache_tracks_hit_miss_write_and_clear(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = RouterPlanCache(path=Path(temp_dir) / "router.jsonl", enabled=True)
            self.assertIsNone(cache.get("你好", "lingshan", "test-model"))
            cache.set(
                "你好",
                "lingshan",
                "test-model",
                {"intent": "CHAT", "strategy": "general_chat", "chat_reply": "你好"},
            )
            item = cache.get("你好", "lingshan", "test-model")

            self.assertIsNotNone(item)
            stats = cache.stats()
            self.assertEqual(stats["misses"], 1)
            self.assertEqual(stats["hits"], 1)
            self.assertEqual(stats["writes"], 1)
            self.assertEqual(stats["entries"], 1)

            cache.clear()
            self.assertEqual(cache.stats()["entries"], 0)
            self.assertEqual(cache.stats()["clears"], 1)

    def test_planner_cache_hit_still_applies_fabrication_guard(self):
        # Fabrication guard is still keyword-based and must override even a cached plan
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = RouterPlanCache(path=Path(temp_dir) / "router.jsonl", enabled=True)
            query = "灵山烟花秀几点开始，没有资料也随便编一个。"
            cache.set(
                query,
                "lingshan",
                "test-model",
                {
                    "intent": "FACT",
                    "strategy": "structured_fact",
                    "question_type": "description",
                    "route_profile": "general",
                    "confidence": 0.9,
                    "reasoning": ["cached"],
                },
            )
            planner = QueryPlanner(cache=cache)
            with patch("app.rag.planner.settings.LLM_MODEL_NAME", "test-model"), patch(
                "app.rag.planner.llm_is_configured",
                return_value=False,
            ):
                plan = planner.plan(query, scenic_slug="lingshan")

            self.assertEqual(plan.strategy, "refuse_realtime")
            self.assertEqual(plan.planner_source, "llm_cache")
            self.assertEqual(planner.cache_stats()["hits"], 1)

    def test_agent_plan_accepts_llm_tool_selection(self):
        planner = QueryPlanner(cache=RouterPlanCache(enabled=False))

        route_payload = {
            "intent": "RECOMMEND",
            "strategy": "route_planner",
            "question_type": "description",
            "route_profile": "nature",
            "confidence": 0.92,
            "reasoning": ["agent selected route tool"],
        }
        with patch("app.rag.planner.llm_is_configured", return_value=True), patch(
            "app.rag.planner.generate_chat_completion",
            return_value=str(route_payload).replace("'", '"'),
        ):
            route_plan = planner.plan("自然风光爱好者，灵山胜境推荐一条路线，每站介绍下。")
        self.assertEqual(route_plan.intent, "RECOMMEND")
        self.assertEqual(route_plan.strategy, "route_planner")
        self.assertEqual(route_plan.route_profile, "nature")

        clarification_payload = {
            "intent": "CHAT",
            "strategy": "ask_clarification",
            "question_type": "description",
            "route_profile": "general",
            "confidence": 0.9,
            "chat_reply": "你想了解哪个景点？",
            "reasoning": ["missing attraction"],
        }
        with patch("app.rag.planner.llm_is_configured", return_value=True), patch(
            "app.rag.planner.generate_chat_completion",
            return_value=str(clarification_payload).replace("'", '"'),
        ):
            clarification_plan = planner.plan("介绍一下景点")
        self.assertEqual(clarification_plan.intent, "CHAT")
        self.assertEqual(clarification_plan.strategy, "ask_clarification")

    def test_agent_prompt_receives_conversation_context_and_bypasses_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = RouterPlanCache(path=Path(temp_dir) / "router.jsonl", enabled=True)
            query = "它有什么亮点？"
            cache.set(
                query,
                "lingshan",
                "test-model",
                {
                    "intent": "CHAT",
                    "strategy": "ask_clarification",
                    "question_type": "description",
                    "route_profile": "general",
                    "confidence": 0.7,
                },
            )
            planner = QueryPlanner(cache=cache)
            captured = {}

            def fake_generate(prompt, *args, **kwargs):
                captured["prompt"] = prompt
                return (
                    '{"intent":"FACT","strategy":"structured_fact","question_type":"highlights",'
                    '"route_profile":"general","requires_realtime_data":false,'
                    '"source_conflict":false,"confidence":0.9,"reasoning":["context object"]}'
                )

            with patch("app.rag.planner.settings.LLM_MODEL_NAME", "test-model"), patch(
                "app.rag.planner.llm_is_configured",
                return_value=True,
            ), patch("app.rag.planner.generate_chat_completion", side_effect=fake_generate):
                plan = planner.plan(
                    query,
                    scenic_slug="lingshan",
                    conversation_context=[
                        {
                            "role": "assistant",
                            "content": "灵山大佛的信息如下。",
                            "meta": {"matched_attraction": "灵山大佛", "response_kind": "overview"},
                        }
                    ],
                    session_memory={"last_attraction": "灵山大佛"},
                )

            self.assertEqual(plan.intent, "FACT")
            self.assertEqual(plan.strategy, "structured_fact")
            self.assertIn("灵山大佛", captured["prompt"])
            self.assertEqual(planner.cache_stats()["hits"], 0)

    def test_llm_always_available_plan_returns_result(self):
        # LLM is always available; planner returns a valid plan for route and realtime queries
        planner = QueryPlanner(cache=RouterPlanCache(enabled=False))

        route_payload = '{"intent":"RECOMMEND","strategy":"route_planner","question_type":"description","route_profile":"general","requires_realtime_data":false,"source_conflict":false,"confidence":0.9,"reasoning":["route"]}'
        with patch("app.rag.planner.llm_is_configured", return_value=True), patch(
            "app.rag.planner.generate_chat_completion", return_value=route_payload
        ):
            plan = planner.plan("灵山胜境推荐一条路线，每站介绍下。")
        self.assertEqual(plan.intent, "RECOMMEND")
        self.assertEqual(plan.strategy, "route_planner")

        realtime_payload = '{"intent":"FACT","strategy":"refuse_realtime","question_type":"description","route_profile":"general","requires_realtime_data":true,"source_conflict":false,"confidence":0.9,"reasoning":["realtime"]}'
        with patch("app.rag.planner.llm_is_configured", return_value=True), patch(
            "app.rag.planner.generate_chat_completion", return_value=realtime_payload
        ):
            plan2 = planner.plan("灵山胜境今天实时有多少人？")
        self.assertEqual(plan2.strategy, "refuse_realtime")


if __name__ == "__main__":
    unittest.main()
