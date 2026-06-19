import unittest
from unittest.mock import patch

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

    def test_fact_semantic_agent_uses_llm_structured_plan(self):
        payload = (
            '{"attraction_name":"灵山大照壁","question_type":"location","evidence_mode":"structured",'
            '"is_comparison":false,"compared_attractions":[],"confidence":0.92,"reasoning":"询问景点位置。"}'
        )

        with patch("app.rag.fact_agent.llm_is_configured", return_value=True), patch(
            "app.rag.fact_agent.generate_chat_completion", return_value=payload
        ) as generate:
            plan = self.agent._plan_with_fact_semantic_agent(
                "灵山大照壁在哪儿？",
                scenic_slug=None,
                context_row=None,
                retrieval_mode="structured_only",
                planned_question_type=None,
            )

        self.assertTrue(generate.called)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.attraction_name, "灵山大照壁")
        self.assertEqual(plan.question_type, "location")
        self.assertEqual(plan.planner_source, "fact_semantic_agent")

    def test_fact_semantic_agent_rejects_unknown_field(self):
        plan = self.agent._plan_from_fact_semantic_payload(
            {
                "attraction_name": "灵山大照壁",
                "question_type": "made_up_field",
                "evidence_mode": "structured",
            },
            scenic_slug=None,
        )

        self.assertIsNone(plan)


if __name__ == "__main__":
    unittest.main()
