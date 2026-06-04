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

    def test_planner_cache_hit_still_applies_local_postprocessing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = RouterPlanCache(path=Path(temp_dir) / "router.jsonl", enabled=True)
            query = "五智门在游览路线上起啥作用？"
            cache.set(
                query,
                "lingshan",
                "test-model",
                {
                    "intent": "RECOMMEND",
                    "strategy": "route_planner",
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

            self.assertEqual(plan.intent, "FACT")
            self.assertEqual(plan.strategy, "structured_fact")
            self.assertEqual(plan.planner_source, "llm_cache")
            self.assertEqual(planner.cache_stats()["hits"], 1)

    def test_heuristic_routes_core_cases(self):
        planner = QueryPlanner(cache=RouterPlanCache(enabled=False))

        route_plan = planner.plan("自然风光爱好者，灵山胜境推荐一条路线，每站介绍下。")
        self.assertEqual(route_plan.intent, "RECOMMEND")
        self.assertEqual(route_plan.strategy, "route_planner")
        self.assertEqual(route_plan.route_profile, "nature")

        fact_plan = planner.plan("五智门在游览路线上起啥作用？")
        self.assertEqual(fact_plan.intent, "FACT")
        self.assertEqual(fact_plan.strategy, "structured_fact")

        analytics_plan = planner.plan("豫园一般逛多久？")
        self.assertEqual(analytics_plan.intent, "ANALYTICS")
        self.assertEqual(analytics_plan.strategy, "semantic_sql")


if __name__ == "__main__":
    unittest.main()
