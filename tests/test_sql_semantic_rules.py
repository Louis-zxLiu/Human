import unittest

from app.rag.sql_agent import TouristAnalyticsAgent


class SQLSemanticRulesTests(unittest.TestCase):
    def setUp(self):
        self.agent = TouristAnalyticsAgent(db_path="missing-test-db.sqlite")

    def test_type_dimension_for_top_attraction_types(self):
        plan = self.agent._plan_semantic_query("2025年4月哪5种景点去的人最多？")

        self.assertIsNotNone(plan)
        self.assertEqual(plan.metric_key, "visits")
        self.assertEqual(plan.dimension_key, "attraction_type")
        self.assertEqual(plan.limit, 5)

    def test_name_dimension_for_top_attractions(self):
        plan = self.agent._plan_semantic_query("哪5个景点去的人最多？")

        self.assertIsNotNone(plan)
        self.assertEqual(plan.metric_key, "visits")
        self.assertEqual(plan.dimension_key, "attraction_name")
        self.assertEqual(plan.limit, 5)

    def test_avg_stay_metric_for_colloquial_duration_question(self):
        plan = self.agent._plan_semantic_query("游客一般逛多久？")

        self.assertIsNotNone(plan)
        self.assertEqual(plan.metric_key, "avg_stay")
        self.assertEqual(plan.query_mode, "scalar")

    def test_avg_total_cost_metric_for_colloquial_spending_question(self):
        plan = self.agent._plan_semantic_query("游客平均在景区花多少钱？")

        self.assertIsNotNone(plan)
        self.assertEqual(plan.metric_key, "avg_total_cost")
        self.assertEqual(plan.query_mode, "scalar")

    def test_semantic_renderer_uses_natural_label_and_rounded_value(self):
        plan = self.agent._plan_semantic_query("游客平均在景区花多少钱？")
        answer = self.agent._render_semantic_result(plan, [{"avg_total_cost": 692.89}])

        self.assertIn("平均总消费约为692.89元", answer)
        self.assertNotIn("avg_total_cost", answer)
        self.assertNotIn("692.886", answer)

    def test_semantic_agent_payload_is_validated_into_safe_plan(self):
        plan = self.agent._plan_from_semantic_agent_payload(
            {
                "metric_key": "avg_total_cost",
                "dimension_key": None,
                "query_mode": "scalar",
                "order": "desc",
                "limit": None,
                "filters": [],
                "confidence": 0.94,
                "reasoning": "询问平均总消费。",
            }
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan.metric_key, "avg_total_cost")
        self.assertEqual(plan.planner_source, "analytics_semantic_agent")

    def test_semantic_agent_payload_rejects_unknown_metric(self):
        plan = self.agent._plan_from_semantic_agent_payload(
            {
                "metric_key": "drop_table",
                "dimension_key": None,
                "query_mode": "scalar",
                "filters": [],
            }
        )

        self.assertIsNone(plan)


if __name__ == "__main__":
    unittest.main()
