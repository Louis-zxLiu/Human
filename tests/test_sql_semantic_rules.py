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


if __name__ == "__main__":
    unittest.main()
