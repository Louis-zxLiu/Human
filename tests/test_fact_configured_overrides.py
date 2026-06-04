import unittest

from app.rag.fact_agent import ScenicFactAgent


class FactConfiguredOverridesTests(unittest.TestCase):
    def setUp(self):
        self.agent = ScenicFactAgent()

    def test_configured_override_answers_precise_structured_fact(self):
        answer = self.agent._answer_configured_structured_override(
            "灵山大佛多高多重？",
            "灵山大佛",
            "architecture_params",
        )

        self.assertIsNotNone(answer)
        self.assertIn("88", answer)
        self.assertIn("725", answer)

    def test_configured_override_respects_docx_exclusion(self):
        answer = self.agent._answer_configured_structured_override(
            "评委问灵山大佛高度材质该答什么关键事实？",
            "灵山大佛",
            "architecture_params",
        )

        self.assertIsNone(answer)

    def test_configured_override_respects_question_type(self):
        answer = self.agent._answer_configured_structured_override(
            "五印坛城在哪里？",
            "五印坛城",
            "location",
        )

        self.assertIsNotNone(answer)
        self.assertIn("香水海", answer)

    def test_fact_rules_detect_source_conflict(self):
        self.assertTrue(self.agent._has_source_conflict("用游客行为数据证明灵山大佛多高。"))

    def test_fact_rules_prefer_structured_for_plain_precise_field(self):
        self.assertFalse(
            self.agent._prefers_docx_evidence(
                "五印坛城在哪里？",
                retrieval_mode="structured_only",
                attraction="五印坛城",
                question_type="location",
            )
        )

    def test_fact_rules_prefer_docx_for_judge_evidence_prompt(self):
        self.assertTrue(
            self.agent._prefers_docx_evidence(
                "评委问灵山大佛高度材质该答什么关键事实？",
                retrieval_mode="structured_only",
                attraction="灵山大佛",
                question_type="architecture_params",
            )
        )


if __name__ == "__main__":
    unittest.main()
