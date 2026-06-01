import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.rag.fact_agent import ScenicFactAgent
from app.rag.llm_client import generate_chat_completion


CURRENT_POSITION_HINTS = (
    "我现在",
    "当前位置",
    "当前所在",
    "我在哪",
    "我在哪里",
    "我附近",
    "附近",
    "周边",
    "离我最近",
    "从这里",
    "从这儿",
    "接下来",
    "下一步",
)

NEXT_STEP_HINTS = (
    "下一步",
    "接下来",
    "后面去哪",
    "先去哪里",
    "适合去哪些点",
    "附近有什么",
    "离我最近",
)

ROUTE_GUIDANCE_HINTS = (
    "怎么走",
    "怎么去",
    "往哪走",
    "导航",
    "带我去",
    "去怎么走",
)

STATIC_LOCATION_FACT_HINTS = (
    "在哪里",
    "在哪",
    "哪里",
    "位于",
    "什么位置",
    "具体方位",
    "方位",
)


def should_request_landmark_follow_up(user_query: str, intent: str) -> bool:
    query = str(user_query or "").strip()
    if not query:
        return False

    has_current_position_hint = any(keyword in query for keyword in CURRENT_POSITION_HINTS)
    has_route_guidance_hint = any(keyword in query for keyword in ROUTE_GUIDANCE_HINTS)
    has_static_location_hint = any(keyword in query for keyword in STATIC_LOCATION_FACT_HINTS)
    has_next_step_hint = any(keyword in query for keyword in NEXT_STEP_HINTS)

    if has_current_position_hint:
        return True
    if intent == "RECOMMEND" and has_next_step_hint:
        return True
    if has_route_guidance_hint and not has_static_location_hint:
        return True
    return False


def detect_landmark_follow_up_need(user_query: str, intent: str) -> bool:
    query = str(user_query or "").strip()
    normalized_intent = str(intent or "").strip().upper() or "FACT"
    if not query:
        return False

    system_prompt = (
        "You classify whether a weak-GPS follow-up is needed in a scenic-guide assistant. "
        "Return strict JSON only with fields: needs_landmark_follow_up, reason. "
        "Set needs_landmark_follow_up to true only when the user's question depends on their current position, "
        "nearby landmarks, next step from where they currently are, or route guidance from here. "
        "Set it to false for static scenic fact questions such as asking where an attraction is located, "
        "asking for attraction introductions, history, highlights, or general route planning that does not depend on current position."
    )
    prompt = (
        f"User intent: {normalized_intent}\n"
        f"User query: {query}\n\n"
        "Examples:\n"
        '- "灵山梵宫在哪里？" -> false\n'
        '- "从这里怎么去灵山梵宫？" -> true\n'
        '- "我现在 GPS 不太准，下一步适合去哪些点？" -> true\n'
        '- "请推荐一条适合亲子的路线。" -> false\n\n'
        'Output JSON: {"needs_landmark_follow_up": true/false, "reason": "..."}'
    )

    try:
        raw = generate_chat_completion(
            prompt,
            system_prompt,
            temperature=0.0,
            max_tokens=120,
            return_error_text=False,
        )
        cleaned = str(raw or "").replace("```json", "").replace("```", "").strip()
        if cleaned:
            payload = json.loads(cleaned)
            value = payload.get("needs_landmark_follow_up")
            if isinstance(value, bool):
                return value
    except Exception:
        pass
    return should_request_landmark_follow_up(query, normalized_intent)


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
    "拈花广场": ["广场", "拈花", "入口", "塔影"],
    "梵天花海": ["花海", "花田", "大片花", "彩色花海"],
    "香月花街": ["花街", "主街", "店铺", "街区", "夜市"],
    "拈花堂": ["拈花堂", "堂", "禅修", "展演"],
    "五灯湖": ["湖", "五灯湖", "灯影", "水岸", "荷花灯"],
    "鹿鸣谷": ["鹿鸣谷", "山谷", "静修", "禅院"],
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
        self.scenic_sequences: Dict[str, List[str]] = {}
        for attraction_name in self.scenic_order:
            row = fact_agent.get_attraction_row(attraction_name)
            if not row:
                continue
            scenic_name = str(row.get("scenic_name") or "").strip()
            self.scenic_sequences.setdefault(scenic_name, []).append(attraction_name)

    def is_navigation_query(self, user_query: str) -> bool:
        return any(keyword in user_query for keyword in ("位置", "在哪", "哪里", "怎么走", "路线", "导航", "从这里"))

    def infer_candidates(
        self,
        landmark_description: str,
        top_k: int = 3,
        scenic_slug: Optional[str] = None,
    ) -> List[CandidateLocation]:
        allowed_attractions = set(self.fact_agent.list_attractions(scenic_slug=scenic_slug))
        candidates: List[CandidateLocation] = []
        for attraction_name, keywords in LANDMARK_HINTS.items():
            if allowed_attractions and attraction_name not in allowed_attractions:
                continue
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
        return "当前 GPS 信号较弱，我先不能准确定位您。请描述一下您附近最明显的佛像、桥、广场、宫殿、塔、花海、湖面或街区，我再结合景点资料继续帮您判断。"

    def build_candidate_reply(
        self,
        candidates: List[CandidateLocation],
        original_query: str,
    ) -> Dict[str, Any]:
        if not candidates:
            return {
                "gps_state": "need_more_landmarks",
                "answer": "我还不能根据刚才的描述准确定位。请再补充一个更明显的地标，比如大佛、梵宫、九龙灌浴、花海、五灯湖、寺院、桥或坛城。",
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
        start_row = self.fact_agent.get_attraction_row(start)
        end_row = self.fact_agent.get_attraction_row(end)
        if not start_row or not end_row:
            return f"{start} -> {end}"
        if start_row.get("scenic_name") != end_row.get("scenic_name"):
            return f"{start} -> {end}"
        scenic_sequence = self.scenic_sequences.get(start_row.get("scenic_name"), [])
        if start not in scenic_sequence or end not in scenic_sequence:
            return f"{start} -> {end}"
        start_index = scenic_sequence.index(start)
        end_index = scenic_sequence.index(end)
        if start_index <= end_index:
            segment = scenic_sequence[start_index : end_index + 1]
        else:
            segment = [start, end]
        return " -> ".join(segment)

    def _get_next_stops(self, current_attraction: str, count: int = 2) -> List[str]:
        row = self.fact_agent.get_attraction_row(current_attraction)
        if not row:
            return []
        scenic_sequence = self.scenic_sequences.get(row.get("scenic_name"), [])
        if current_attraction not in scenic_sequence:
            return []
        index = scenic_sequence.index(current_attraction)
        return scenic_sequence[index + 1 : index + 1 + count]
