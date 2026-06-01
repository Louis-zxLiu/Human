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

    def test_weather_query_is_rejected_as_realtime_required(self):
        result = self.pipeline.process_query("今天下午灵山胜境会不会下雨？")
        self.assertEqual(result["response_kind"], "refused:realtime_required")
        self.assertIsNotNone(result["refusal"])
        self.assertEqual(result["refusal"]["reason"], "realtime_required")

    def test_live_traffic_query_is_rejected_as_realtime_required(self):
        result = self.pipeline.process_query("从无锡市区到灵山胜境现在堵不堵？")
        self.assertEqual(result["response_kind"], "refused:realtime_required")
        self.assertIsNotNone(result["refusal"])
        self.assertEqual(result["refusal"]["reason"], "realtime_required")

    def test_comparison_query_does_not_collapse_to_first_attraction(self):
        result = self.pipeline.process_query("灵山梵宫和五印坛城哪个更适合给游客讲建筑艺术？")
        self.assertEqual(result["response_kind"], "comparison:architecture_params")
        self.assertIsNone(result["matched_attraction"])
        self.assertIn("灵山梵宫", result["answer"])
        self.assertIn("五印坛城", result["answer"])

    def test_reference_query_resolves_target_instead_of_anchor(self):
        result = self.pipeline.process_query("灵山梵宫旁边的那个藏式建筑是什么？")
        self.assertEqual(result["matched_attraction"], "五印坛城")
        self.assertTrue(result["response_kind"] in {"field:description", "field:architecture_params", "overview"})
        self.assertIn("五印坛城", result["answer"])


    def test_recommendation_exposes_compact_answer_for_cached_route_flow(self):
        result = self.pipeline.process_query(
            "\u6211\u662f\u5386\u53f2\u6587\u5316\u7231\u597d\u8005\uff0c\u8bf7\u63a8\u8350\u4e00\u6761\u7075\u5c71\u80dc\u5883\u8def\u7ebf\uff0c\u5e76\u8bf4\u660e\u6bcf\u7ad9\u8bb2\u4ec0\u4e48\u3002"
        )
        self.assertEqual(result["response_kind"], "recommendation")
        recommendation = result["recommendation"]
        self.assertIsNotNone(recommendation)
        self.assertGreaterEqual(len(recommendation.get("route_items") or []), 3)
        compact_answer = recommendation.get("compact_answer", "")
        self.assertIn("\u8be6\u7ec6\u5b89\u6392\u89c1\u4e0b\u65b9\u8def\u7ebf\u5361\u7247", compact_answer)
        self.assertNotIn("\u6bcf\u7ad9\u8bb2\u89e3\u5efa\u8bae", compact_answer)


if __name__ == "__main__":
    unittest.main()
