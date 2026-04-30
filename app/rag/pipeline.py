from typing import Any, Dict

from app.rag.fact_agent import ScenicFactAgent, extract_interest_label
from app.rag.recommendation_agent import ScenicRecommendationAgent
from app.rag.router import get_query_intent
from app.rag.sql_agent import TouristAnalyticsAgent


class ScenicRAGPipeline:
    """
    Unified runtime pipeline.

    FACT:
      Scenic fact questions answered from the Lingshan scenic knowledge layer.
    ANALYTICS:
      Visitor behavior questions answered from the behavior table only.
    RECOMMEND:
      Scenic route recommendation built from scenic facts, with analytics as a secondary hint.
    """

    def __init__(self):
        self.fact_agent = ScenicFactAgent()
        self.analytics_agent = TouristAnalyticsAgent()
        self.recommendation_agent = ScenicRecommendationAgent(
            fact_agent=self.fact_agent,
            analytics_agent=self.analytics_agent,
        )

    def process_query(self, user_query: str) -> Dict[str, Any]:
        intent = get_query_intent(user_query)

        if intent == "ANALYTICS":
            answer = self.analytics_agent.query(user_query)
            return {
                "query": user_query,
                "intent": intent,
                "agent_type": "behavior_analytics",
                "answer": answer,
                "matched_attraction": None,
                "recommendation_label": None,
                "response_kind": "analytics",
            }

        if intent == "RECOMMEND":
            result = self.recommendation_agent.answer(user_query)
            return {
                "query": user_query,
                "intent": intent,
                "agent_type": "scenic_recommendation",
                "answer": result["answer"],
                "matched_attraction": result.get("matched_attraction"),
                "recommendation_label": result.get("recommendation_label")
                or extract_interest_label(user_query),
                "response_kind": result.get("response_kind", "recommendation"),
            }

        result = self.fact_agent.answer(user_query)
        return {
            "query": user_query,
            "intent": intent,
            "agent_type": "scenic_fact",
            "answer": result["answer"],
            "matched_attraction": result.get("matched_attraction"),
            "recommendation_label": None,
            "response_kind": result.get("response_kind", "fact"),
        }


if __name__ == "__main__":
    pipeline = ScenicRAGPipeline()
    examples = [
        "梵宫开放时间是什么？",
        "灵山大佛有什么历史背景？",
        "女性游客更喜欢哪类景点？",
        "给我推荐一条适合历史爱好者的路线。",
    ]
    for query in examples:
        result = pipeline.process_query(query)
        print("=" * 50)
        print(result["intent"], result["agent_type"])
        print(result["answer"])
