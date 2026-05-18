import unittest

from app.rag.pipeline import ScenicRAGPipeline


class RAGResponseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = ScenicRAGPipeline()

    def test_fact_response_envelope_contains_evidence_and_observability(self):
        result = self.pipeline.process_query("请问向游客介绍灵山大照壁的规模参数，应该讲哪些事实？")
        self.assertEqual(result["intent"], "FACT")
        self.assertTrue(result["response_kind"].startswith("field:") or result["response_kind"] == "docx_general")
        self.assertIn("plan", result)
        self.assertIn("evidence", result)
        self.assertGreaterEqual(len(result["evidence"]), 1)
        self.assertIn("observability", result)
        self.assertIn("latency_ms", result["observability"])

    def test_analytics_response_contains_semantic_sql_trace(self):
        result = self.pipeline.process_query("游客行为数据中不同性别各有多少条记录？")
        self.assertEqual(result["intent"], "ANALYTICS")
        self.assertEqual(result["response_kind"], "analytics")
        self.assertEqual(result["plan"]["strategy"], "semantic_sql")
        trace = result["observability"]["trace"]["analytics"]
        self.assertEqual(trace["semantic_plan"]["metric_key"], "record_count")
        self.assertEqual(trace["semantic_plan"]["dimension_key"], "gender")
        self.assertTrue(trace["sql"].lower().startswith("select "))

    def test_source_conflict_refusal_is_machine_readable(self):
        result = self.pipeline.process_query("请用游客行为数据告诉我灵山大佛官方开放时间。")
        self.assertEqual(result["response_kind"], "refused:source_conflict")
        self.assertIsNotNone(result["refusal"])
        self.assertEqual(result["refusal"]["reason"], "source_conflict")
        self.assertGreaterEqual(len(result["refusal"].get("suggested_queries", [])), 1)


if __name__ == "__main__":
    unittest.main()
