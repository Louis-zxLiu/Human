from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.core.scenic_catalog import (
    SCENIC_ROUTE_PROFILES,
    get_scenic_entry,
    infer_scenic_slug_from_text,
    scenic_name_from_slug,
    scenic_slug_from_name,
)
from app.rag.fact_agent import ScenicFactAgent
from app.rag.llm_client import generate_chat_completion
from app.rag.response_contract import make_evidence
from app.rag.sql_agent import TouristAnalyticsAgent


PROFILE_LABELS: Dict[str, str] = {
    "history": "历史文化",
    "nature": "风景打卡",
    "family": "亲子同游",
    "architecture": "建筑艺术",
    "relaxed": "轻松慢游",
    "general": "经典首游",
}

PLANNER_DURATION_NOTES = {
    "short": "控制在较轻量的半日节奏里，优先保留辨识度最高的节点。",
    "half-day": "维持半日游节奏，适合比赛演示或周末白天体验。",
    "full-day": "保留更完整的漫游与停留空间，适合整日体验。",
    "night-tour": "更强调入夜后的氛围、灯光和慢行体验。",
}
PLANNER_VISITOR_NOTES = {
    "solo": "适合一个人边走边听讲解，路线更强调清晰感和可追问性。",
    "couple": "更适合拍照、夜景和氛围感停留。",
    "family": "优先保留互动性、开阔度和中途休息点。",
    "elder": "建议减少折返和节奏过快的节点，强调舒适停留。",
    "friends": "适合一起拍照、快速浏览和集中体验代表性节点。",
}
PLANNER_PACE_NOTES = {
    "compact": "整体节奏偏紧凑，适合时间有限的快速体验。",
    "balanced": "整体节奏均衡，兼顾讲解、拍照和停留。",
    "relaxed": "整体节奏更舒缓，鼓励多停留和慢慢感受氛围。",
}


def get_recommendation_display_label(label: str) -> str:
    normalized = str(label or "").strip().lower()
    return PROFILE_LABELS.get(normalized, str(label or "").strip())


def detect_interest_label_clean(user_query: str) -> str:
    query = str(user_query or "").strip().lower()
    rules: List[Tuple[str, Tuple[str, ...]]] = [
        ("history", ("历史", "文化", "人文", "佛教", "禅意")),
        ("nature", ("自然", "风光", "湖景", "拍照", "打卡", "花海")),
        ("family", ("亲子", "孩子", "老人", "家庭")),
        ("architecture", ("建筑", "艺术", "工艺", "梵宫", "坛城", "街区", "立面")),
        ("relaxed", ("轻松", "慢游", "不累", "休闲", "夜游")),
    ]
    for label, keywords in rules:
        if any(keyword in query for keyword in keywords):
            return label
    return "general"


def classify_interest_label(user_query: str) -> str:
    system_prompt = (
        "You classify scenic-tour recommendation preference labels. "
        "Return strict JSON only with one field: label. "
        "The label must be exactly one of: history, nature, family, architecture, relaxed, general."
    )
    prompt = f"""
用户问题：{user_query}

标签说明：
- history：偏历史、文化、人文、佛教讲解
- nature：偏风景、拍照、打卡、自然景观
- family：偏亲子、家庭、老人、儿童同行
- architecture：偏建筑、艺术、传统工艺、空间设计、街区立面
- relaxed：偏轻松、慢游、休闲、不赶路、夜游
- general：无法明确归入以上类别时使用

请输出 JSON：
{{
  "label": "..."
}}
"""
    try:
        raw = generate_chat_completion(prompt, system_prompt, temperature=0.1)
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        import json

        payload = json.loads(cleaned)
        label = str(payload.get("label") or "").strip().lower()
        if label in PROFILE_LABELS:
            return label
    except Exception:
        pass
    return detect_interest_label_clean(user_query)


def normalize_interest_label(label: Optional[str]) -> str:
    value = str(label or "").strip().lower()
    return value if value in PROFILE_LABELS else "general"


class ScenicRecommendationAgent:
    """Produce scenic recommendations that are aware of which scenic area is active."""

    def __init__(self, fact_agent: ScenicFactAgent, analytics_agent: TouristAnalyticsAgent):
        self.fact_agent = fact_agent
        self.analytics_agent = analytics_agent

    def answer(
        self,
        user_query: str,
        start_attraction: Optional[str] = None,
        user_profile: Optional[str] = None,
        scenic_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_scenic_slug = self._resolve_scenic_slug(user_query, scenic_slug, start_attraction)
        profile_key = self._refine_label_with_profile(classify_interest_label(user_query), user_profile)
        return self._build_recommendation(
            scenic_slug=resolved_scenic_slug,
            profile_key=profile_key,
            start_attraction=start_attraction,
            planning_context=None,
            user_profile=user_profile,
        )

    def plan_route(
        self,
        scenic_slug: str,
        interest_label: str,
        duration_band: str = "half-day",
        visitor_type: str = "solo",
        pace: str = "balanced",
    ) -> Dict[str, Any]:
        planning_context = {
            "duration_band": duration_band,
            "visitor_type": visitor_type,
            "pace": pace,
        }
        return self._build_recommendation(
            scenic_slug=scenic_slug,
            profile_key=normalize_interest_label(interest_label),
            start_attraction=None,
            planning_context=planning_context,
            user_profile=None,
        )

    def _build_recommendation(
        self,
        scenic_slug: str,
        profile_key: str,
        start_attraction: Optional[str],
        planning_context: Optional[Dict[str, str]],
        user_profile: Optional[str],
    ) -> Dict[str, Any]:
        scenic_entry = get_scenic_entry(scenic_slug) or get_scenic_entry("lingshan-shengjing")
        scenic_slug = scenic_entry["slug"]
        scenic_name = scenic_entry["scenic_name"]
        profile_map = SCENIC_ROUTE_PROFILES[scenic_slug]
        profile = profile_map.get(profile_key) or profile_map["general"]
        display_label = get_recommendation_display_label(profile_key)
        route_rows = self._collect_route(profile["attractions"], scenic_slug, start_attraction)
        analytics_hint = self.analytics_agent.get_preference_hint(profile["analytics_types"])
        route_items = [
            {
                "order": index,
                "name": row["attraction_name"],
                "summary": self._short_reason(row),
                "rationale": self._stop_rationale(row, profile_key),
                "attractionId": row["attraction_id"],
                "evidence": make_evidence(
                    "structured_fact_db",
                    "attractions",
                    entity=row["attraction_name"],
                    field="route_stop",
                    snippet=row.get("highlights") or row.get("description") or row.get("remarks") or "",
                    metadata={"scenic_name": scenic_name},
                ),
            }
            for index, row in enumerate(route_rows, start=1)
        ]
        planning_note = self._compose_planning_note(planning_context)
        profile_text = (
            f" 结合您最近的偏好记录，系统会优先强化 {display_label} 方向的讲解。"
            if user_profile
            else ""
        )
        answer_lines = [
            f"{scenic_name}推荐路线：{' -> '.join(item['name'] for item in route_items)}",
            f"推荐主题：{display_label}",
            f"适合原因：{profile['reason']}{profile_text}",
            f"预计游览时长：{profile['estimated_duration']}",
            f"建议讲解重点：{profile['highlights']}",
            f"游客行为分析补充：{analytics_hint or '当前行为分析层暂时无额外补充，建议以景点讲解体验为主。'}",
        ]
        if route_items:
            stop_lines = [f"{item['order']}. {item['name']}：{item['rationale']}" for item in route_items]
            answer_lines.append("每站讲解建议：" + " ".join(stop_lines))
        if planning_note:
            answer_lines.append(f"规划说明：{planning_note}")
        if start_attraction:
            answer_lines.append(f"建议从 {start_attraction} 附近开始进入这条路线。")
        answer = "\n".join(answer_lines).strip()
        compact_answer = self._build_compact_answer(
            scenic_name=scenic_name,
            title=profile["title"],
            reason=profile["reason"],
            estimated_duration=profile["estimated_duration"],
            route_items=route_items,
            start_attraction=start_attraction,
        )
        first_route_item = route_items[0] if route_items else None
        guide_prompt = (
            f"请以数字人导游的方式带我走一条{scenic_name}的{display_label}路线，"
            f"从{first_route_item['name'] if first_route_item else scenic_name}开始，重点讲{profile['highlights']}。"
        )
        return {
            "answer": answer,
            "compact_answer": compact_answer,
            "matched_attraction": first_route_item["name"] if first_route_item else None,
            "response_kind": "recommendation",
            "recommendation_label": display_label,
            "recommendation": {
                "label": display_label,
                "profile_key": profile_key,
                "title": profile["title"],
                "route_items": route_items,
                "reason": profile["reason"],
                "estimated_duration": profile["estimated_duration"],
                "highlights": profile["highlights"],
                "analytics_hint": analytics_hint,
                "start_attraction": start_attraction,
                "scenic_slug": scenic_slug,
                "scenic_name": scenic_name,
                "guide_prompt": guide_prompt,
                "planning_note": planning_note,
                "compact_answer": compact_answer,
            },
            "evidence": [item["evidence"] for item in route_items[:4]],
            "trace": {
                "profile_key": profile_key,
                "route_stop_count": len(route_items),
                "used_behavior_hint": bool(analytics_hint),
                "planning_context": planning_context or {},
            },
            "profileKey": profile_key,
            "scenicSlug": scenic_slug,
            "scenicName": scenic_name,
            "title": profile["title"],
            "reason": profile["reason"],
            "estimatedDuration": profile["estimated_duration"],
            "highlights": profile["highlights"],
            "analyticsHint": analytics_hint,
            "routeItems": route_items,
            "guidePrompt": guide_prompt,
            "planningNote": planning_note,
        }

    def _build_compact_answer(
        self,
        scenic_name: str,
        title: str,
        reason: str,
        estimated_duration: str,
        route_items: List[Dict[str, Any]],
        start_attraction: Optional[str],
    ) -> str:
        stop_names = [item["name"] for item in route_items[:3] if item.get("name")]
        stops_text = "\u3001".join(stop_names) if stop_names else scenic_name
        answer = (
            f"\u63a8\u8350\u8def\u7ebf\uff1a{title}\uff08\u7ea6 {estimated_duration}\uff09\u3002"
            f"\u9002\u5408{reason}\uff0c\u91cd\u70b9\u5305\u542b{stops_text}\u3002"
            "\u8be6\u7ec6\u5b89\u6392\u89c1\u4e0b\u65b9\u8def\u7ebf\u5361\u7247\u3002"
        )
        if start_attraction:
            answer += f"\u5efa\u8bae\u4ece{start_attraction}\u9644\u8fd1\u5f00\u59cb\u3002"
        return answer

    def _resolve_scenic_slug(
        self,
        user_query: str,
        scenic_slug: Optional[str],
        start_attraction: Optional[str],
    ) -> str:
        if scenic_slug and get_scenic_entry(scenic_slug):
            return scenic_slug

        if start_attraction:
            row = self.fact_agent.get_attraction_row(start_attraction)
            if row:
                matched_slug = scenic_slug_from_name(row.get("scenic_name"))
                if matched_slug:
                    return matched_slug

        matched_attraction = self.fact_agent.match_attraction_name(user_query)
        if matched_attraction:
            row = self.fact_agent.get_attraction_row(matched_attraction)
            if row:
                matched_slug = scenic_slug_from_name(row.get("scenic_name"))
                if matched_slug:
                    return matched_slug

        inferred = infer_scenic_slug_from_text(user_query)
        if inferred:
            return inferred
        return "lingshan-shengjing"

    @staticmethod
    def _refine_label_with_profile(label: str, user_profile: Optional[str]) -> str:
        if label != "general" or not user_profile:
            return label
        for candidate, display in PROFILE_LABELS.items():
            if candidate == "general":
                continue
            if candidate in user_profile or display in user_profile:
                return candidate
        return label

    def _collect_route(
        self,
        attraction_names: List[str],
        scenic_slug: str,
        start_attraction: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        route_rows: List[Dict[str, Any]] = []
        scenic_name = scenic_name_from_slug(scenic_slug)
        for attraction_name in attraction_names:
            row = self.fact_agent.get_attraction_row(attraction_name)
            if row and row.get("scenic_name") == scenic_name:
                route_rows.append(row)

        if not start_attraction:
            return route_rows

        names = [row["attraction_name"] for row in route_rows]
        if start_attraction in names:
            index = names.index(start_attraction)
            return route_rows[index:] + route_rows[:index]

        start_row = self.fact_agent.get_attraction_row(start_attraction)
        if start_row and start_row.get("scenic_name") == scenic_name:
            return [start_row] + route_rows
        return route_rows

    @staticmethod
    def _compose_planning_note(planning_context: Optional[Dict[str, str]]) -> str:
        if not planning_context:
            return ""
        notes = []
        duration = planning_context.get("duration_band")
        visitor_type = planning_context.get("visitor_type")
        pace = planning_context.get("pace")
        if duration in PLANNER_DURATION_NOTES:
            notes.append(PLANNER_DURATION_NOTES[duration])
        if visitor_type in PLANNER_VISITOR_NOTES:
            notes.append(PLANNER_VISITOR_NOTES[visitor_type])
        if pace in PLANNER_PACE_NOTES:
            notes.append(PLANNER_PACE_NOTES[pace])
        return " ".join(notes)

    @staticmethod
    def _short_reason(row: Dict[str, Any]) -> str:
        for field in ("highlights", "description", "remarks", "core_function"):
            value = str(row.get(field) or "").strip()
            if value:
                return value[:72] + ("..." if len(value) > 72 else "")
        return "适合作为本路线的讲解节点。"

    @staticmethod
    def _stop_rationale(row: Dict[str, Any], profile_key: str) -> str:
        profile_prompts = {
            "history": ("cultural_meaning", "description", "remarks"),
            "nature": ("highlights", "location", "description"),
            "family": ("highlights", "description", "remarks"),
            "architecture": ("architecture_params", "description", "cultural_meaning"),
            "relaxed": ("remarks", "highlights", "location"),
            "general": ("description", "highlights", "cultural_meaning"),
        }
        fields = profile_prompts.get(profile_key, profile_prompts["general"])
        for field in fields:
            value = str(row.get(field) or "").strip()
            if value:
                return value[:88] + ("..." if len(value) > 88 else "")
        return "适合作为这条路线中的代表性停留点。"
