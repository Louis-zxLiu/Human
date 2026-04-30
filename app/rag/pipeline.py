from typing import Any, Dict, Optional

from app.rag.fact_agent import ScenicFactAgent, extract_interest_label
from app.rag.recommendation_agent import ScenicRecommendationAgent
from app.rag.router import get_query_intent
from app.rag.sql_agent import TouristAnalyticsAgent


class ScenicRAGPipeline:
    """Unified runtime pipeline for FACT / ANALYTICS / RECOMMEND."""

    def __init__(self):
        self.fact_agent = ScenicFactAgent()
        self.analytics_agent = TouristAnalyticsAgent()
        self.recommendation_agent = ScenicRecommendationAgent(
            fact_agent=self.fact_agent,
            analytics_agent=self.analytics_agent,
        )

    def process_query(
        self,
        user_query: str,
        user_profile: Optional[str] = None,
        start_attraction: Optional[str] = None,
    ) -> Dict[str, Any]:
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
                "recommendation": None,
            }

        if intent == "RECOMMEND":
            result = self.recommendation_agent.answer(
                user_query,
                start_attraction=start_attraction,
                user_profile=user_profile,
            )
            return {
                "query": user_query,
                "intent": intent,
                "agent_type": "scenic_recommendation",
                "answer": result["answer"],
                "matched_attraction": result.get("matched_attraction"),
                "recommendation_label": result.get("recommendation_label") or extract_interest_label(user_query),
                "response_kind": result.get("response_kind", "recommendation"),
                "recommendation": result.get("recommendation"),
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
            "recommendation": None,
        }
