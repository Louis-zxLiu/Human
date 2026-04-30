from typing import Any, Dict, List, Optional

from app.rag.fact_agent import ScenicFactAgent, extract_interest_label
from app.rag.sql_agent import TouristAnalyticsAgent


PROFILE_RULES: Dict[str, Dict[str, Any]] = {
    "history": {
        "title": "历史文化深度路线",
        "reason": "适合希望系统了解灵山佛教文化、建筑寓意和核心讲解脉络的游客。",
        "attractions": ["灵山大照壁", "祥符禅寺", "灵山大佛", "灵山梵宫", "五印坛城"],
        "highlights": "重点听玄奘与小灵山渊源、佛教文化体系、梵宫艺术和藏传文化补充。",
        "estimated_duration": "约3.5到4.5小时",
        "analytics_types": ["历史文化", "博物馆与展馆"],
    },
    "nature": {
        "title": "景观打卡舒展路线",
        "reason": "适合偏爱空间景观、拍照取景和节奏舒缓的游客。",
        "attractions": ["灵山大照壁", "五明桥", "菩提大道", "灵山大佛", "五印坛城"],
        "highlights": "重点看太湖视野、仪式性中轴线、佛像远景和坛城外观取景。",
        "estimated_duration": "约3到4小时",
        "analytics_types": ["风景名胜与休闲度假"],
    },
    "family": {
        "title": "亲子友好路线",
        "reason": "适合家庭同行，路线以易理解、可互动、停留舒适为主。",
        "attractions": ["百子戏弥勒", "九龙灌浴", "佛教文化博览馆", "灵山大佛"],
        "highlights": "重点讲弥勒吉祥寓意、九龙灌浴动态表演和适合孩子理解的佛教常识。",
        "estimated_duration": "约2.5到3.5小时",
        "analytics_types": ["历史文化", "风景名胜与休闲度假"],
    },
    "architecture": {
        "title": "建筑艺术主题路线",
        "reason": "适合关注建筑尺度、工艺细节和空间设计的游客。",
        "attractions": ["阿育王柱", "灵山大佛", "灵山梵宫", "五印坛城", "曼飞龙塔"],
        "highlights": "重点看佛教建筑工艺、轴线布局、材质与多语系佛教建筑风格对比。",
        "estimated_duration": "约3到4小时",
        "analytics_types": ["现代地标", "博物馆与展馆"],
    },
    "relaxed": {
        "title": "轻松慢游路线",
        "reason": "适合不想太赶路、希望边走边听讲解的游客。",
        "attractions": ["灵山大照壁", "五明桥", "菩提大道", "九龙灌浴", "祥符禅寺"],
        "highlights": "重点保留步行体验和核心讲解节点，减少高强度折返。",
        "estimated_duration": "约2.5到3小时",
        "analytics_types": ["风景名胜与休闲度假"],
    },
    "general": {
        "title": "经典首游路线",
        "reason": "适合第一次来到灵山胜境，优先覆盖最具代表性的核心景点。",
        "attractions": ["灵山大照壁", "九龙灌浴", "祥符禅寺", "灵山大佛", "灵山梵宫"],
        "highlights": "重点覆盖入口文化、动态表演、古刹、大佛和梵宫五个核心节点。",
        "estimated_duration": "约3到4小时",
        "analytics_types": ["风景名胜与休闲度假", "历史文化"],
    },
}


class ScenicRecommendationAgent:
    """Produce explanation-first scenic recommendations from facts plus analytics hints."""

    def __init__(self, fact_agent: ScenicFactAgent, analytics_agent: TouristAnalyticsAgent):
        self.fact_agent = fact_agent
        self.analytics_agent = analytics_agent

    def answer(
        self,
        user_query: str,
        start_attraction: Optional[str] = None,
        user_profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        label = self._refine_label_with_profile(extract_interest_label(user_query), user_profile)
        profile = PROFILE_RULES[label]
        route_rows = self._collect_route(profile["attractions"], start_attraction)
        analytics_hint = self.analytics_agent.get_preference_hint(profile["analytics_types"])

        route_items = [
            {
                "name": row["attraction_name"],
                "summary": self._short_reason(row),
            }
            for row in route_rows
        ]
        start_text = f"建议从{start_attraction}附近开始进入这条路线。" if start_attraction else ""
        profile_text = f" 结合您最近的偏好记录，系统会优先强化{label}方向的讲解。" if user_profile else ""

        answer = "\n".join(
            [
                f"推荐路线：{' -> '.join(item['name'] for item in route_items)}",
                f"适合原因：{profile['reason']}{profile_text}",
                f"预计游览时长：{profile['estimated_duration']}",
                f"建议讲解重点：{profile['highlights']}",
                f"游客行为分析补充：{analytics_hint or '当前行为分析层暂无额外补充，建议以景点讲解体验为主。'}",
                start_text,
            ]
        ).strip()

        return {
            "answer": answer,
            "matched_attraction": route_rows[0]["attraction_name"] if route_rows else None,
            "response_kind": "recommendation",
            "recommendation_label": label,
            "recommendation": {
                "label": label,
                "title": profile["title"],
                "route_items": route_items,
                "reason": profile["reason"],
                "estimated_duration": profile["estimated_duration"],
                "highlights": profile["highlights"],
                "analytics_hint": analytics_hint,
                "start_attraction": start_attraction,
            },
        }

    @staticmethod
    def _refine_label_with_profile(label: str, user_profile: Optional[str]) -> str:
        if label != "general" or not user_profile:
            return label
        for candidate in PROFILE_RULES:
            if candidate != "general" and candidate in user_profile:
                return candidate
        return label

    def _collect_route(
        self,
        attraction_names: List[str],
        start_attraction: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        route_rows: List[Dict[str, Any]] = []
        for attraction_name in attraction_names:
            row = self.fact_agent.get_attraction_row(attraction_name)
            if row:
                route_rows.append(row)

        if not start_attraction:
            return route_rows

        names = [row["attraction_name"] for row in route_rows]
        if start_attraction in names:
            index = names.index(start_attraction)
            return route_rows[index:] + route_rows[:index]

        start_row = self.fact_agent.get_attraction_row(start_attraction)
        if start_row:
            return [start_row] + route_rows
        return route_rows

    @staticmethod
    def _short_reason(row: Dict[str, Any]) -> str:
        for field in ("highlights", "description", "remarks", "core_function"):
            value = str(row.get(field) or "").strip()
            if value:
                return value[:60] + ("..." if len(value) > 60 else "")
        return "适合作为本路线的讲解节点。"
