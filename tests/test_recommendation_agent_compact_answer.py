import unittest

from app.rag.recommendation_agent import ScenicRecommendationAgent


class RecommendationCompactAnswerTests(unittest.TestCase):
    def test_compact_answer_avoids_duplicate_duration_and_reason_prefix(self):
        agent = ScenicRecommendationAgent.__new__(ScenicRecommendationAgent)
        result = agent._build_compact_answer(
            scenic_name="\u7075\u5c71\u80dc\u5883",
            title="\u4eb2\u5b50\u53cb\u597d\u8def\u7ebf",
            reason="\u9002\u5408\u5bb6\u5ead\u540c\u884c\uff0c\u8def\u7ebf\u4ee5\u6613\u7406\u89e3\u3001\u53ef\u4e92\u52a8\u548c\u505c\u7559\u8212\u9002\u4e3a\u4e3b\u3002",
            estimated_duration="\u7ea6 2.5 \u5230 3.5 \u5c0f\u65f6",
            route_items=[
                {"name": "\u767e\u5b50\u620f\u5f25\u52d2"},
                {"name": "\u4e5d\u9f99\u704c\u6d74"},
                {"name": "\u4f5b\u6559\u6587\u5316\u535a\u89c8\u9986"},
            ],
            start_attraction=None,
        )
        self.assertNotIn("\u9002\u5408\u9002\u5408", result)
        self.assertNotIn("\u7ea6 \u7ea6", result)
        self.assertIn("\u9002\u5408\u5bb6\u5ead\u540c\u884c", result)
        self.assertIn("\u7ea6 2.5 \u5230 3.5 \u5c0f\u65f6", result)

    def test_forced_profile_key_overrides_query_inference(self):
        result = ScenicRecommendationAgent._resolve_profile_key(
            user_query="\u6211\u60f3\u5728\u62c8\u82b1\u6e7e\u6162\u6162\u901b\uff0c\u4e5f\u5e26\u5b69\u5b50\u4e00\u8d77\u3002",
            user_profile=None,
            forced_profile_key="family",
        )
        self.assertEqual(result, "family")


if __name__ == "__main__":
    unittest.main()
