import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import resolve_path
from app.rag.chroma_agent import ChromaStaticAgent


ATTRACTION_COLUMNS = [
    "scenic_name",
    "attraction_id",
    "attraction_name",
    "location",
    "architecture_params",
    "core_function",
    "cultural_meaning",
    "description",
    "highlights",
    "open_info",
    "remarks",
]


class ScenicFactAgent:
    """Answer scenic fact questions only from the Lingshan scenic knowledge layer."""

    FIELD_ALIASES = {
        "open_info": ("开放", "开放时间", "营业", "几点", "什么时候", "开门", "闭园", "演出时间"),
        "location": ("位置", "在哪", "哪里", "怎么走", "路线", "方位"),
        "highlights": ("亮点", "特色", "看点", "值得看", "必看", "推荐理由"),
        "remarks": ("注意", "提醒", "建议", "打卡", "拍照"),
        "architecture_params": ("建筑", "参数", "规模", "多高", "多大", "造型"),
        "core_function": ("作用", "用途", "功能"),
        "cultural_meaning": ("文化", "寓意", "含义", "象征", "精神"),
        "description": ("介绍", "讲解", "概况", "是什么"),
    }

    HISTORY_KEYWORDS = ("历史", "渊源", "来历", "背景", "故事", "典故", "为什么")

    ATTRACTION_ALIASES = {
        "梵宫": "灵山梵宫",
        "大佛": "灵山大佛",
        "九龙": "九龙灌浴",
        "灌浴": "九龙灌浴",
        "坛城": "五印坛城",
        "禅寺": "祥符禅寺",
        "照壁": "灵山大照壁",
        "佛足": "佛足坛",
        "博览馆": "佛教文化博览馆",
        "弥勒": "百子戏弥勒",
        "阿育王柱": "阿育王柱",
        "五智门": "五智门",
        "五明桥": "五明桥",
        "菩提大道": "菩提大道",
        "降魔浮雕": "降魔浮雕",
        "曼飞龙塔": "曼飞龙塔",
        "无尽意斋": "无尽意斋",
        "灵山胜境": "灵山胜境",
    }

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or resolve_path("data/processed/tourist_behavior.db")
        self._rows = self._load_rows()
        self._rag_agent: Optional[ChromaStaticAgent] = None

    def answer(self, user_query: str) -> Dict[str, Any]:
        attraction = self._match_attraction(user_query)
        field = self._match_field(user_query)
        use_history_rag = self._is_history_question(user_query)

        if attraction and attraction != "灵山胜境":
            row = self._rows.get(attraction)
            if row:
                if use_history_rag:
                    rag_answer = self._query_rag(user_query)
                    if not self._looks_like_missing_answer(rag_answer):
                        return {
                            "answer": rag_answer,
                            "matched_attraction": attraction,
                            "response_kind": "rag_history",
                        }

                if field:
                    text = self._format_field_answer(row, field)
                    if text:
                        return {
                            "answer": text,
                            "matched_attraction": attraction,
                            "response_kind": f"field:{field}",
                        }

                text = self._format_overview(row)
                if text:
                    return {
                        "answer": text,
                        "matched_attraction": attraction,
                        "response_kind": "overview",
                    }

        rag_answer = self._query_rag(user_query)
        if not self._looks_like_missing_answer(rag_answer):
            return {
                "answer": rag_answer,
                "matched_attraction": attraction,
                "response_kind": "rag_general",
            }

        fallback = "抱歉，我暂时没有在灵山胜境知识资料中找到足够证据来回答这个问题。"
        return {
            "answer": fallback,
            "matched_attraction": attraction,
            "response_kind": "refused",
        }

    def list_attractions(self) -> List[str]:
        return list(self._rows.keys())

    def get_attraction_row(self, attraction_name: str) -> Optional[Dict[str, Any]]:
        return self._rows.get(attraction_name)

    def _load_rows(self) -> Dict[str, Dict[str, Any]]:
        rows: Dict[str, Dict[str, Any]] = {}
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            table_exists = cursor.execute(
                "select count(*) from sqlite_master where type='table' and name='attractions'"
            ).fetchone()[0]
            if not table_exists:
                return rows

            for row in cursor.execute(
                f"select {', '.join(ATTRACTION_COLUMNS)} from attractions"
            ).fetchall():
                row_dict = dict(row)
                rows[row_dict["attraction_name"]] = row_dict
        finally:
            conn.close()
        return rows

    def _match_attraction(self, user_query: str) -> Optional[str]:
        normalized = user_query.strip()
        for attraction_name in self._rows:
            if attraction_name in normalized:
                return attraction_name

        for alias, attraction_name in self.ATTRACTION_ALIASES.items():
            if alias in normalized:
                if attraction_name == "灵山胜境":
                    return "灵山胜境"
                if attraction_name in self._rows:
                    return attraction_name
        return None

    def _match_field(self, user_query: str) -> Optional[str]:
        for field, keywords in self.FIELD_ALIASES.items():
            if any(keyword in user_query for keyword in keywords):
                return field
        return None

    def _is_history_question(self, user_query: str) -> bool:
        return any(keyword in user_query for keyword in self.HISTORY_KEYWORDS)

    def _format_field_answer(self, row: Dict[str, Any], field: str) -> Optional[str]:
        value = (row.get(field) or "").strip()
        if not value:
            return None

        attraction = row["attraction_name"]
        templates = {
            "open_info": f"{attraction}的开放信息是：{value}",
            "location": f"{attraction}的位置是：{value}",
            "highlights": f"{attraction}的主要看点包括：{value}",
            "remarks": f"{attraction}的游览建议是：{value}",
            "architecture_params": f"{attraction}的建筑与规模信息是：{value}",
            "core_function": f"{attraction}的核心功能是：{value}",
            "cultural_meaning": f"{attraction}的文化内涵是：{value}",
            "description": f"{attraction}的景点介绍是：{value}",
        }
        return templates.get(field)

    def _format_overview(self, row: Dict[str, Any]) -> Optional[str]:
        attraction = row["attraction_name"]
        parts = []
        if row.get("description"):
            parts.append(f"景点介绍：{row['description'].strip()}")
        if row.get("location"):
            parts.append(f"所在位置：{row['location'].strip()}")
        if row.get("architecture_params"):
            parts.append(f"规模信息：{row['architecture_params'].strip()}")
        if row.get("cultural_meaning"):
            parts.append(f"文化内涵：{row['cultural_meaning'].strip()}")
        if row.get("highlights"):
            parts.append(f"主要看点：{row['highlights'].strip()}")
        if row.get("open_info"):
            parts.append(f"开放信息：{row['open_info'].strip()}")

        if not parts:
            return None
        return f"{attraction}的信息如下。" + " ".join(parts)

    def _query_rag(self, user_query: str) -> str:
        if self._rag_agent is None:
            self._rag_agent = ChromaStaticAgent()
        return self._rag_agent.query(user_query)

    @staticmethod
    def _looks_like_missing_answer(answer: str) -> bool:
        if not answer:
            return True
        patterns = [
            "知识库中暂未收录",
            "暂时没有在",
            "未找到相关内容",
            "不太了解",
            "请联系管理员",
        ]
        return any(pattern in answer for pattern in patterns)


def extract_interest_label(user_query: str) -> str:
    query = user_query.lower()
    rules: List[Tuple[str, Tuple[str, ...]]] = [
        ("history", ("历史", "文化", "人文", "佛教", "禅意")),
        ("nature", ("自然", "风光", "湖景", "拍照", "打卡")),
        ("family", ("亲子", "孩子", "老人", "家庭")),
        ("architecture", ("建筑", "艺术", "梵宫", "坛城")),
        ("relaxed", ("轻松", "慢游", "不累", "休闲")),
    ]
    for label, keywords in rules:
        if any(keyword in query for keyword in keywords):
            return label
    return "general"
