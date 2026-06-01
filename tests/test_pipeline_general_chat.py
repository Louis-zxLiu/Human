import unittest
from unittest.mock import patch

from app.rag.pipeline import ScenicRAGPipeline, detect_general_chat_reply


class PipelineGeneralChatTests(unittest.TestCase):
    def test_llm_screening_routes_greeting_to_short_chat_reply(self):
        pipeline = ScenicRAGPipeline()
        with patch(
            "app.rag.pipeline.generate_chat_completion",
            return_value='{"is_general_chat": true, "reply": "\\u4f60\\u597d\\uff0c\\u6211\\u5728\\u3002", "reason": "greeting"}',
        ):
            result = pipeline.process_query("\u4f60\u597d")
        self.assertEqual(result["intent"], "CHAT")
        self.assertEqual(result["agent_type"], "general_chat")
        self.assertEqual(result["response_kind"], "chat")
        self.assertEqual(result["answer"], "\u4f60\u597d\uff0c\u6211\u5728\u3002")

    def test_llm_screening_does_not_divert_scenic_question(self):
        pipeline = ScenicRAGPipeline()
        with patch(
            "app.rag.pipeline.generate_chat_completion",
            return_value='{"is_general_chat": false, "reason": "scenic fact"}',
        ):
            result = pipeline.process_query("\u4f60\u597d\uff0c\u7075\u5c71\u5927\u4f5b\u5728\u54ea\u91cc\uff1f")
        self.assertNotEqual(result["response_kind"], "chat")
        self.assertNotEqual(result["intent"], "CHAT")

    def test_fallback_heuristic_still_handles_plain_thanks(self):
        with patch("app.rag.pipeline.generate_chat_completion", return_value="not-json"):
            reply = detect_general_chat_reply("\u8c22\u8c22")
        self.assertEqual(reply, "\u4e0d\u5ba2\u6c14\uff0c\u6211\u5728\u3002")


if __name__ == "__main__":
    unittest.main()
