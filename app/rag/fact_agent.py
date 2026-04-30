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


SUPPLEMENTAL_FACTS: Dict[str, Dict[str, str]] = {
    "灵山大佛": {
        "core_function": "灵山胜境的核心礼佛地标，也是游客俯瞰景区中轴线和太湖景观的重要节点。",
        "cultural_meaning": "作为神州五方五佛之一的东方佛，灵山大佛象征佛教文化在江南地区的弘扬，也承载着祈福平安、感悟慈悲智慧的文化内涵。",
        "description": "灵山大佛是灵山胜境最具代表性的核心景观，以露天青铜释迦牟尼立像著称，整体空间庄严开阔，和祥符禅寺、梵宫等景点共同构成景区主轴。",
        "highlights": "可近距离感受大佛体量与仪式感，登临相关观景区域俯瞰太湖与景区全貌，也是游客拍照打卡和集中讲解的重点景点。",
        "open_info": "通常随灵山胜境景区开放时间同步开放，建议游客结合当日景区公告或官方购票页面确认最新开放安排。",
        "remarks": "若计划拍摄大佛全景，建议在天气通透时前往；如需重点礼佛或听讲解，可将此处安排在主游线中段或后段。",
    }
}


QUESTION_FIELD_MAP: Dict[str, Tuple[str, ...]] = {
    "open_info": ("开放", "开放时间", "营业", "几点", "什么时候", "开门", "闭园", "演出时间", "门票"),
    "location": ("位置", "在哪", "哪里", "怎么走", "路线", "方位", "导航"),
    "history": ("历史", "来历", "渊源", "背景", "故事", "典故", "为什么"),
    "cultural_meaning": ("文化", "寓意", "含义", "象征", "精神"),
    "highlights": ("亮点", "特色", "看点", "值得看", "必看", "推荐理由"),
    "remarks": ("建议", "注意", "提醒", "打卡", "拍照"),
    "architecture_params": ("建筑", "规模", "多高", "多大", "造型", "参数"),
    "core_function": ("作用", "用途", "功能"),
    "description": ("介绍", "讲解", "概况", "是什么"),
}


class ScenicFactAgent:
    """Use the Lingshan scenic fact layer as the single trusted source for fact Q&A."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or resolve_path("data/processed/tourist_behavior.db")
        self._rows = self._load_rows()
        self._rag_agent: Optional[ChromaStaticAgent] = None
        self._attraction_aliases = self._build_aliases()

    def answer(self, user_query: str) -> Dict[str, Any]:
        attraction = self.match_attraction_name(user_query)
        question_type = self.detect_question_type(user_query)

        if attraction and attraction != "灵山胜境":
            row = self._rows.get(attraction)
            if row:
                if question_type == "history":
                    text = self._format_history_answer(row)
                    if text:
                        return self._result(text, attraction, "history")

                if question_type in row:
                    text = self._format_field_answer(row, question_type)
                    if text:
                        return self._result(text, attraction, f"field:{question_type}")

                overview = self._format_overview(row)
                if overview:
                    return self._result(overview, attraction, "overview")

        rag_answer = self._query_rag(user_query)
        if rag_answer and not self._looks_like_missing_answer(rag_answer):
            return self._result(rag_answer, attraction, "rag_general")

        follow_up = self._build_refusal_follow_up(question_type, attraction)
        return self._result(follow_up, attraction, "refused")

    def list_attractions(self) -> List[str]:
        return list(self._rows.keys())

    def get_attraction_row(self, attraction_name: str) -> Optional[Dict[str, Any]]:
        return self._rows.get(attraction_name)

    def match_attraction_name(self, user_query: str) -> Optional[str]:
        query = user_query.strip()
        for attraction_name in self._rows:
            if attraction_name in query:
                return attraction_name

        for alias, attraction_name in self._attraction_aliases.items():
            if alias in query:
                return attraction_name
        return None

    def detect_question_type(self, user_query: str) -> str:
        for field, keywords in QUESTION_FIELD_MAP.items():
            if any(keyword in user_query for keyword in keywords):
                return field
        return "description"

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

            for row in cursor.execute(f"select {', '.join(ATTRACTION_COLUMNS)} from attractions").fetchall():
                row_dict = dict(row)
                row_dict = self._merge_supplemental_facts(row_dict)
                rows[row_dict["attraction_name"]] = row_dict
        finally:
            conn.close()
        return rows

    def _merge_supplemental_facts(self, row: Dict[str, Any]) -> Dict[str, Any]:
        supplements = SUPPLEMENTAL_FACTS.get(row["attraction_name"], {})
        for key, value in supplements.items():
            if not str(row.get(key) or "").strip():
                row[key] = value
        return row

    def _build_aliases(self) -> Dict[str, str]:
        return {
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
            "王柱": "阿育王柱",
            "五智门": "五智门",
            "五明桥": "五明桥",
            "菩提大道": "菩提大道",
            "降魔浮雕": "降魔浮雕",
            "曼飞龙塔": "曼飞龙塔",
            "无尽意斋": "无尽意斋",
            "灵山胜境": "灵山胜境",
        }

    def _format_field_answer(self, row: Dict[str, Any], field: str) -> Optional[str]:
        value = str(row.get(field) or "").strip()
        if not value:
            return None

        attraction = row["attraction_name"]
        templates = {
            "open_info": f"{attraction}的开放信息是：{value}",
            "location": f"{attraction}的位置是：{value}",
            "cultural_meaning": f"{attraction}的文化内涵是：{value}",
            "highlights": f"{attraction}的特色和主要看点包括：{value}",
            "remarks": f"{attraction}的游览建议是：{value}",
            "architecture_params": f"{attraction}的建筑与规模信息是：{value}",
            "core_function": f"{attraction}的核心功能是：{value}",
            "description": f"{attraction}的景点介绍是：{value}",
        }
        return templates.get(field)

    def _format_history_answer(self, row: Dict[str, Any]) -> Optional[str]:
        attraction = row["attraction_name"]
        parts = []
        if row.get("description"):
            parts.append(str(row["description"]).strip())
        if row.get("cultural_meaning"):
            parts.append(f"文化寓意上，{str(row['cultural_meaning']).strip()}")
        if row.get("remarks"):
            parts.append(f"游览补充上，{str(row['remarks']).strip()}")
        if not parts:
            return None
        return f"{attraction}的历史与背景可以这样理解：{' '.join(parts)}"

    def _format_overview(self, row: Dict[str, Any]) -> Optional[str]:
        attraction = row["attraction_name"]
        parts = []
        for label, field in (
            ("景点介绍", "description"),
            ("所在位置", "location"),
            ("规模信息", "architecture_params"),
            ("文化内涵", "cultural_meaning"),
            ("主要看点", "highlights"),
            ("开放信息", "open_info"),
            ("游览建议", "remarks"),
        ):
            value = str(row.get(field) or "").strip()
            if value:
                parts.append(f"{label}：{value}")
        if not parts:
            return None
        return f"{attraction}的信息如下。{' '.join(parts)}"

    def _query_rag(self, user_query: str) -> str:
        if self._rag_agent is None:
            self._rag_agent = ChromaStaticAgent()
        return self._rag_agent.query(user_query)

    def _build_refusal_follow_up(self, question_type: str, attraction: Optional[str]) -> str:
        if attraction:
            return f"抱歉，我暂时没有在灵山胜境资料中找到关于{attraction}这部分内容的充分证据。您可以换一种问法，或者改问它的位置、开放信息、看点或文化内涵。"
        if question_type == "location":
            return "抱歉，我暂时无法直接判断您问的是哪一个灵山景点。您可以补充景点名称，或者描述一下附近最明显的建筑、佛像、桥或广场。"
        return "抱歉，我暂时没有在灵山胜境知识资料中找到足够证据来回答这个问题。您可以补充具体景点名称，或者改问位置、开放信息、历史背景、亮点和游览建议。"

    def _looks_like_missing_answer(self, answer: str) -> bool:
        if not answer:
            return True
        patterns = [
            "暂未初始化",
            "暂未收录",
            "暂时不了解",
            "建议您可以去服务台咨询",
            "没有在灵山胜境知识资料中找到",
        ]
        return any(pattern in answer for pattern in patterns)

    @staticmethod
    def _result(answer: str, attraction: Optional[str], response_kind: str) -> Dict[str, Any]:
        return {
            "answer": answer,
            "matched_attraction": attraction,
            "response_kind": response_kind,
        }


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
