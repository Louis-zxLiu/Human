import unittest
from unittest.mock import patch

from app.rag.location_agent import detect_landmark_follow_up_need


class LocationAgentDetectionTests(unittest.TestCase):
    def test_llm_marks_static_location_question_as_no_follow_up(self):
        query = "\u7075\u5c71\u68b5\u5bab\u5728\u54ea\u91cc\uff1f"
        with patch(
            "app.rag.location_agent.generate_chat_completion",
            return_value='{"needs_landmark_follow_up": false, "reason": "static location question"}',
        ):
            self.assertFalse(detect_landmark_follow_up_need(query, "FACT"))

    def test_llm_marks_from_here_navigation_question_as_follow_up(self):
        query = "\u4ece\u8fd9\u91cc\u600e\u4e48\u53bb\u7075\u5c71\u68b5\u5bab\uff1f"
        with patch(
            "app.rag.location_agent.generate_chat_completion",
            return_value='{"needs_landmark_follow_up": true, "reason": "depends on current position"}',
        ):
            self.assertTrue(detect_landmark_follow_up_need(query, "FACT"))

    def test_fallback_keeps_general_recommendation_out_of_weak_gps_flow(self):
        query = "\u8bf7\u63a8\u8350\u4e00\u6761\u9002\u5408\u4eb2\u5b50\u7684\u8def\u7ebf\u3002"
        with patch("app.rag.location_agent.generate_chat_completion", return_value="not-json"):
            self.assertFalse(detect_landmark_follow_up_need(query, "RECOMMEND"))

    def test_fallback_keeps_next_step_question_in_weak_gps_flow(self):
        query = "\u6211\u73b0\u5728GPS\u4e0d\u592a\u51c6\uff0c\u4e0b\u4e00\u6b65\u9002\u5408\u53bb\u54ea\u4e9b\u70b9\uff1f"
        with patch("app.rag.location_agent.generate_chat_completion", return_value="not-json"):
            self.assertTrue(detect_landmark_follow_up_need(query, "RECOMMEND"))


if __name__ == "__main__":
    unittest.main()
