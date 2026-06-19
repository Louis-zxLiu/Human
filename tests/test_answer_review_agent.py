import unittest
from unittest.mock import patch

from app.rag.answer_review_agent import AnswerReviewAgent


class AnswerReviewAgentTests(unittest.TestCase):
    def test_llm_reviewer_audits_without_rewriting(self):
        agent = AnswerReviewAgent()
        reviewer_payload = (
            '{"approved": false, '
            '"issues": ["field_name_leak", "unformatted_number"], "risk_level": "minor", '
            '"repair_action": "call_behavior_sql", "reasoning": "字段名和长小数需要主 Agent 重新调用分析子 Agent。"}'
        )

        with patch("app.rag.answer_review_agent.llm_is_configured", return_value=True), patch(
            "app.rag.answer_review_agent.generate_chat_completion", return_value=reviewer_payload
        ) as generate:
            reviewed = agent.review(
                user_query="游客平均在景区花多少钱？",
                result={
                    "answer": "基于游客行为数据分析，avg_cost为692.8865164795261。",
                    "response_kind": "analytics:fallback",
                    "warnings": [],
                    "trace": {},
                },
                agent_type="behavior_analytics",
            )

        self.assertTrue(generate.called)
        self.assertEqual(reviewed["answer"], "基于游客行为数据分析，avg_cost为692.8865164795261。")
        self.assertIn("answer_review:not_approved", reviewed["warnings"])
        self.assertTrue(reviewed["trace"]["answer_review"]["checked"])
        self.assertEqual(reviewed["trace"]["answer_review"]["reviewer"], "llm")
        self.assertFalse(reviewed["trace"]["answer_review"]["approved"])
        self.assertEqual(reviewed["trace"]["answer_review"]["repair_action"], "call_behavior_sql")

    def test_reviewer_marks_unavailable_when_llm_is_not_configured(self):
        agent = AnswerReviewAgent()

        with patch("app.rag.answer_review_agent.llm_is_configured", return_value=False), patch(
            "app.rag.answer_review_agent.generate_chat_completion"
        ) as generate:
            reviewed = agent.review(
                user_query="你好",
                result={"answer": "你好，我在。", "response_kind": "chat", "warnings": [], "trace": {}},
                agent_type="general_chat",
            )

        self.assertFalse(generate.called)
        self.assertEqual(reviewed["answer"], "你好，我在。")
        self.assertIn("answer_review:llm_unavailable", reviewed["warnings"])
        self.assertIn("answer_review:not_approved", reviewed["warnings"])
        self.assertFalse(reviewed["trace"]["answer_review"]["checked"])
        self.assertFalse(reviewed["trace"]["answer_review"]["approved"])
        self.assertEqual(reviewed["trace"]["answer_review"]["repair_action"], "retry_same_agent")


if __name__ == "__main__":
    unittest.main()
