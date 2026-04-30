from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.rag.fact_agent import ScenicFactAgent


LANDMARK_HINTS: Dict[str, List[str]] = {
    "灵山大照壁": ["照壁", "入口", "太湖", "大字", "广场"],
    "五明桥": ["桥", "五明桥", "水面"],
    "佛足坛": ["佛足", "脚印", "佛脚"],
    "五智门": ["门", "五智门", "牌坊"],
    "菩提大道": ["大道", "菩提树", "中轴线", "步道"],
    "九龙灌浴": ["九龙", "灌浴", "喷泉", "莲花", "演出区"],
    "降魔浮雕": ["浮雕", "石刻", "降魔"],
    "阿育王柱": ["王柱", "高柱", "石柱"],
    "百子戏弥勒": ["弥勒", "百子", "孩童雕塑"],
    "祥符禅寺": ["禅寺", "寺院", "殿", "香火", "银杏"],
    "灵山大佛": ["大佛", "巨佛", "佛像", "高处", "主地标"],
    "佛教文化博览馆": ["博览馆", "展馆", "馆内"],
    "灵山梵宫": ["梵宫", "穹顶", "宫殿", "壁画", "木雕"],
    "五印坛城": ["坛城", "藏式", "转经筒", "白墙金顶"],
    "曼飞龙塔": ["塔", "白塔", "南传"],
    "无尽意斋": ["斋", "休息区", "素斋"],
}


@dataclass
class CandidateLocation:
    attraction_name: str
    score: int
    matched_keywords: List[str]


class ScenicLocationAgent:
    """Infer likely scenic locations from landmarks for weak-GPS conversations."""

    def __init__(self, fact_agent: ScenicFactAgent):
        self.fact_agent = fact_agent
        self.scenic_order = sorted(
            fact_agent.list_attractions(),
            key=lambda name: (fact_agent.get_attraction_row(name) or {}).get("attraction_id", ""),
        )

    def is_navigation_query(self, user_query: str) -> bool:
        return any(keyword in user_query for keyword in ("位置", "在哪", "哪里", "怎么走", "路线", "导航", "从这里"))

    def infer_candidates(self, landmark_description: str, top_k: int = 3) -> List[CandidateLocation]:
        candidates: List[CandidateLocation] = []
        for attraction_name, keywords in LANDMARK_HINTS.items():
            matched = [keyword for keyword in keywords if keyword in landmark_description]
            if matched:
                candidates.append(
                    CandidateLocation(
                        attraction_name=attraction_name,
                        score=len(matched),
                        matched_keywords=matched,
                    )
                )
        candidates.sort(key=lambda item: (-item.score, item.attraction_name))
        return candidates[:top_k]

    def build_follow_up_prompt(self) -> str:
        return "当前 GPS 信号较弱，我先不能准确定位您。请描述一下您附近最明显的佛像、桥、广场、宫殿、塔或演出区，我再结合灵山景点资料继续帮您判断。"

    def build_candidate_reply(
        self,
        candidates: List[CandidateLocation],
        original_query: str,
    ) -> Dict[str, Any]:
        if not candidates:
            return {
                "gps_state": "need_more_landmarks",
                "answer": "我还不能根据刚才的描述准确定位。请再补充一个更明显的地标，比如大佛、梵宫、九龙灌浴、寺院、桥或坛城。",
                "resolved_attraction": None,
                "candidate_names": [],
            }

        if len(candidates) > 1 and candidates[0].score == candidates[1].score:
            names = [candidate.attraction_name for candidate in candidates]
            return {
                "gps_state": "ambiguous",
                "answer": f"根据您的描述，我更像在{names[0]}或{names[1]}附近。请再确认一下，您是否能看到{'、'.join(candidates[0].matched_keywords[:2])}之外的明显标志？",
                "resolved_attraction": None,
                "candidate_names": names,
            }

        best = candidates[0]
        route_text = self._build_navigation_suggestion(best.attraction_name, original_query)
        return {
            "gps_state": "resolved",
            "answer": f"我推测您现在更可能在{best.attraction_name}附近，因为您提到了{'、'.join(best.matched_keywords)}。{route_text}",
            "resolved_attraction": best.attraction_name,
            "candidate_names": [candidate.attraction_name for candidate in candidates],
        }

    def _build_navigation_suggestion(self, current_attraction: str, original_query: str) -> str:
        target_attraction = self.fact_agent.match_attraction_name(original_query)
        if target_attraction and target_attraction != current_attraction:
            route = self._build_linear_route(current_attraction, target_attraction)
            return f"如果您想去{target_attraction}，建议按“{route}”这条主游线继续前行。"

        next_stops = self._get_next_stops(current_attraction, count=2)
        if next_stops:
            return f"您可以从这里继续前往{next_stops[0]}，再衔接到{next_stops[1] if len(next_stops) > 1 else '后续核心景点'}。"
        return "建议您沿景区主游线继续前行，并留意现场导览牌或工作人员指引。"

    def _build_linear_route(self, start: str, end: str) -> str:
        if start not in self.scenic_order or end not in self.scenic_order:
            return f"{start} -> {end}"
        start_index = self.scenic_order.index(start)
        end_index = self.scenic_order.index(end)
        if start_index <= end_index:
            segment = self.scenic_order[start_index : end_index + 1]
        else:
            segment = [start, end]
        return " -> ".join(segment)

    def _get_next_stops(self, current_attraction: str, count: int = 2) -> List[str]:
        if current_attraction not in self.scenic_order:
            return []
        index = self.scenic_order.index(current_attraction)
        return self.scenic_order[index + 1 : index + 1 + count]
