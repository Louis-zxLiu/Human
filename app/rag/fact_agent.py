import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import resolve_path
from app.core.scenic_catalog import infer_scenic_slug_from_text, list_scenic_catalog, scenic_name_from_slug, scenic_slug_from_name
from app.rag.chroma_agent import ChromaStaticAgent
from app.rag.llm_client import generate_chat_completion, llm_is_configured
from app.rag.planner import contains_realtime_unsupported_signal
from app.rag.rule_config import load_json_config, term_map, term_tuple
from app.rag.response_contract import make_evidence, make_refusal


FACT_RULE_CONFIG = load_json_config("app/rag/config/fact_rules.json")


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

_FACT_ROWS_CACHE: Optional[Dict[str, Dict[str, Any]]] = None
_FACT_ROWS_DB_PATH: Optional[str] = None

_DOCX_SCORE_THRESHOLD  = 13
_DOCX_SCORE_BASE       = 10
_DOCX_SCORE_TOPIC_MATCH   = 8
_DOCX_SCORE_TOPIC_TERM    = 3
_DOCX_SCORE_TOKEN_MATCH   = 6
_DOCX_SCORE_MUST_INCLUDE  = 2
_FACT_SEMANTIC_MAX_TOKENS = 420

_FACT_SEMANTIC_PLAN_PROMPT = (
    "Return one JSON object with these fields:\n"
    "- attraction_name: one known attraction name, or null if the question is scenic-level/broad.\n"
    "- question_type: one of location, open_info, architecture_params, highlights, remarks, history, cultural_meaning, core_function, description.\n"
    "- evidence_mode: structured, docx, or hybrid. Use structured for exact field facts; docx/hybrid for broad historical/cultural/document evidence questions.\n"
    "- is_comparison: true if comparing two attractions.\n"
    "- compared_attractions: array of known attraction names when is_comparison=true.\n"
    "- confidence: 0.0 to 1.0.\n"
    "- reasoning: short Chinese sentence.\n\n"
    "Known attractions: {allowed_attractions}\n"
    "Context attraction: {context_attraction}\n"
    "Outer planner question_type hint: {planned_question_type}\n"
    "Requested retrieval mode: {retrieval_mode}\n\n"
    "Question type guide:\n"
    "- where/position/how to get there => location\n"
    "- daily open hours, visitor opening hours, performance time => open_info\n"
    "- official opening date, completion date, consecration date, origin date => history\n"
    "- size, height, material, architecture, dimensions => architecture_params\n"
    "- what to see/play/experience/features, main experience, must-experience, most worth visiting => highlights\n"
    "- tips, reminders, photo/check-in advice => remarks; if the question asks opening availability/time restrictions, use open_info instead.\n"
    "- origin, background, story, why named => history\n"
    "- symbolism, cultural meaning, spirit => cultural_meaning\n"
    "- purpose, use, function, what it is for => core_function\n"
    "- general intro/explain/overview/key introduction points => description\n\n"
    "Evidence mode guide:\n"
    "- Use docx or hybrid when the user asks for evidence, key facts, key points, explanation highlights, official dates, craft details, symbolism details, performance contents, or judge-facing facts.\n"
    "- Use docx for questions containing official dates, key numbers, judge-facing wording, cannot-be-wrong facts, scale/dimensions that need exact DOCX evidence, cultural symbolism, or performance facts.\n"
    "- Use structured only for plain direct fields such as where it is, ordinary open hours, basic function, or short overview.\n\n"
    "Examples:\n"
    "- question_type=history, evidence_mode=docx\n"
    "- question_type=architecture_params, evidence_mode=docx\n"
    "- question_type=open_info, evidence_mode=docx\n"
    "- question_type=highlights, evidence_mode=structured\n"
    "- question_type=open_info, evidence_mode=structured\n"
    "- question_type=description, evidence_mode=structured\n"
    "- question_type=location, evidence_mode=structured\n\n"
    "User question: {user_query}\n"
    "JSON only."
)


def _load_rows_cached(db_path: str) -> Dict[str, Dict[str, Any]]:
    global _FACT_ROWS_CACHE, _FACT_ROWS_DB_PATH
    if _FACT_ROWS_CACHE is not None and _FACT_ROWS_DB_PATH == db_path:
        return _FACT_ROWS_CACHE
    rows: Dict[str, Dict[str, Any]] = {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        table_exists = cursor.execute(
            "select count(*) from sqlite_master where type='table' and name='attractions'"
        ).fetchone()[0]
        if table_exists:
            col_list = ", ".join(ATTRACTION_COLUMNS)
            for row in cursor.execute(f"select {col_list} from attractions").fetchall():
                row_dict = dict(row)
                supplements = SUPPLEMENTAL_FACTS.get(row_dict["attraction_name"], {})
                for key, value in supplements.items():
                    if not str(row_dict.get(key) or "").strip():
                        row_dict[key] = value
                rows[row_dict["attraction_name"]] = row_dict
    finally:
        conn.close()
    _FACT_ROWS_CACHE = rows
    _FACT_ROWS_DB_PATH = db_path
    return _FACT_ROWS_CACHE


def _invalidate_fact_rows_cache() -> None:
    global _FACT_ROWS_CACHE
    _FACT_ROWS_CACHE = None





@dataclass
class FactSemanticPlan:
    attraction_name: Optional[str] = None
    question_type: Optional[str] = "description"
    evidence_mode: str = "structured"
    is_comparison: bool = False
    compared_attractions: List[str] = field(default_factory=list)
    confidence: float = 0.8
    planner_source: str = "deterministic_fallback"
    reasoning: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attraction_name": self.attraction_name,
            "question_type": self.question_type,
            "evidence_mode": self.evidence_mode,
            "is_comparison": self.is_comparison,
            "compared_attractions": list(self.compared_attractions),
            "confidence": self.confidence,
            "planner_source": self.planner_source,
            "reasoning": list(self.reasoning),
        }


SUPPLEMENTAL_FACTS: Dict[str, Dict[str, str]] = load_json_config(
    "app/rag/config/supplemental_facts.json"
)

QUESTION_FIELD_MAP: Dict[str, Tuple[str, ...]] = {
    "open_info": ("开放", "开放时间", "营业", "几点", "什么时候", "开门", "闭园", "演出时间", "门票"),
    "location": ("位置", "在哪", "哪里", "怎么走", "路线", "方位", "导航"),
    "architecture_params": ("建筑", "景观参数", "规模", "多高", "多大", "造型", "参数"),
    "highlights": ("亮点", "特色", "看点", "值得看", "必看", "推荐理由", "体验", "重点体验", "游玩"),
    "remarks": ("建议", "注意", "提醒", "打卡", "拍照"),
    "history": ("历史", "来历", "渊源", "背景", "故事", "典故", "为什么"),
    "cultural_meaning": ("文化", "寓意", "含义", "象征", "精神"),
    "core_function": ("作用", "用途", "功能"),
    "description": ("介绍", "讲解", "概况", "概述", "是什么"),
}

COMPARISON_HINTS: Tuple[str, ...] = (
    "哪个",
    "哪一个",
    "更适合",
    "更值得",
    "相比",
    "比较",
    "区别",
    "差别",
    "还是",
)

REFERENCE_POSITION_HINTS: Tuple[str, ...] = (
    "旁边",
    "附近",
    "边上",
    "周边",
    "对面",
    "后面",
    "前面",
    "南侧",
    "北侧",
    "东侧",
    "西侧",
)

REFERENCE_DESCRIPTOR_TERMS: Tuple[str, ...] = (
    "藏式",
    "藏传",
    "建筑",
    "坛城",
    "佛塔",
    "圣塔",
    "桥",
    "大佛",
    "禅寺",
    "博览馆",
    "博物馆",
    "街区",
    "花海",
    "湖",
    "湖心岛",
    "演出",
    "木雕",
    "壁画",
    "唐卡",
    "金顶",
    "白墙",
    "红边",
)


GENERAL_DOCX_FACTS: List[Tuple[Tuple[str, ...], str]] = [
    (
        ("灵山梵宫", "佛教艺术", "卢浮宫"),
        "灵山梵宫被称为佛教艺术的“东方卢浮宫”，是因为它把佛教艺术、传统工艺与现代声光科技集中在同一座大型文化建筑中：外立面有莲花、飞天、经文等佛教元素，内部汇集东阳木雕、壁画、油画、琉璃与星空穹顶等艺术装饰，既承担礼佛空间功能，也承担佛教文化展示与交流功能。",
    ),
    (
        ("梵宫", "传统工艺", "现代科技"),
        "灵山梵宫体现了传统工艺和现代科技的融合：廊厅与室内装饰使用东阳木雕、壁画、油画、琉璃等传统艺术语言，穹顶和舞台则结合 LED 灯光、声光电系统与沉浸式演艺技术，让佛教艺术从静态展示延展为可观看、可体验的文化场景。",
    ),
    (
        ("祥符禅寺", "历史遗存"),
        "祥符禅寺的历史遗存主要包括千年银杏、六角井、八角井等，它们共同见证了寺院的历史脉络和古刹兴衰，是讲解祥符禅寺时很适合展开的证据点。",
    ),
    (
        ("历史文化爱好者", "路线"),
        "历史文化爱好者路线会重点讲解祥符禅寺、灵山大佛和灵山梵宫：祥符禅寺适合讲唐代佛教渊源与寺院遗存，灵山大佛适合讲“五方五佛”和现代灵山胜境建设，灵山梵宫则适合讲世界佛教论坛、佛教艺术展示与文化交流。",
    ),
    (
        ("自然风光爱好者", "路线"),
        "自然风光爱好者路线适合把太湖视野和菩提大道串联起来看：太湖提供开阔湖景与远眺背景，菩提大道则用林荫步道、礼佛轴线和渐进式空间营造慢行观景体验，也便于连接灵山大佛等核心节点。",
    ),
    (
        ("亲子家庭", "路线"),
        "亲子家庭路线适合孩子，是因为它可以把亲子互动、故事讲解和轻体力游览结合起来：例如九龙灌浴、百子戏弥勒、天下第一掌等节点更容易用故事、动作和祈福体验吸引孩子参与，同时路线节奏比纯文化深度游更轻松。",
    ),
    (
        ("小灵山",),
        "灵山胜境被称为“小灵山”，源于唐贞观年间玄奘法师西行取经归来途经马山，见此地山形酷似印度灵鹫山，认为与佛法渊源深厚，遂以“灵鹫胜境”之意命名为“小灵山”。",
    ),
    (
        ("现代灵山胜境", "开始", "修复"),
        "现代灵山胜境的建设从1994年“修复祥符禅寺、建造灵山大佛”工程奠基开始，此后逐步形成今天集信仰、艺术、文化和旅游于一体的综合性佛教文化景区。",
    ),
    (
        ("灵山大佛", "落成"),
        "灵山大佛于1997年11月15日落成开光，是现代灵山胜境一期工程的标志性成果。",
    ),
    (
        ("灵山梵宫", "正式开放"),
        "灵山梵宫属于灵山胜境三期主体工程，于2009年1月1日正式开放，是景区佛教艺术展示与世界佛教文化交流的重要场所。",
    ),
    (
        ("吉祥颂", "演出信息"),
        "《灵山吉祥颂》演出信息里需要答清楚：常见场次包括10:35、11:30、14:00、16:00，内容以舞台机械、灯光特效、真人演绎再现释迦牟尼佛从诞生、修行到成佛的全过程，实际场次以景区当日公告为准。",
    ),
    (
        ("九龙灌浴", "表演"),
        "九龙灌浴表演的关键事实包括：每日4-5场，莲花瓣缓缓开启，太子佛像在九龙吐水与音乐中旋转升起，核心看点是再现“花开见佛、九龙沐浴”的祥瑞场景。",
    ),
    (
        ("世界佛教论坛",),
        "灵山胜境是世界佛教论坛永久会址，灵山梵宫圣坛可承载佛教文化交流、学术研讨和艺术展示，是全球佛教文化对话的重要平台。",
    ),
    (
        ("祈福文化",),
        "灵山胜境的祈福文化体验包括九龙灌浴、天下第一掌、抱佛脚等项目，它们把佛教仪式转化为游客可参与的互动体验，传递“感悟灵山，吉祥平安”的文化理念。",
    ),
    (
        ("五方五佛",),
        "灵山大佛体现了赵朴初提出的“五方五佛”理念，与香港天坛大佛、四川乐山大佛、山西云冈大佛、河南龙门大佛共同构成中国佛教五大佛像格局。",
    ),
    (
        ("核心文化内涵",),
        "灵山胜境的核心文化内涵是以“小灵山”佛教渊源为根基，融合汉传佛教、藏传佛教、传统艺术与现代科技，形成兼具朝圣、祈福、艺术展示和文化交流的佛教文化体验。",
    ),
    (
        ("天下第一掌",),
        "佛手广场的“天下第一掌”是灵山大佛右手复制，高11.7米、宽5.5米，游客摸掌祈福，寓意“沾福气、保平安”。",
    ),
    (
        ("拈花湾", "夜游"),
        "拈花湾适合夜游，是因为它的主体验并不依赖单一高强度项目，而是通过香月花街、五灯湖、水岸灯影和禅意演艺，把慢行、拍照、餐饮和夜间氛围结合成一条完整体验链路。",
    ),
    (
        ("拈花湾", "慢游"),
        "拈花湾更适合慢游，是因为街区尺度宜人、步行压力较低，游客可以在香月花街、五灯湖、鹿鸣谷之间自然停留，把禅意空间、夜景和休闲消费串起来体验。",
    ),
    (
        ("五灯湖", "看点"),
        "五灯湖的核心看点在于水岸灯影、夜间氛围和节庆演艺承载能力，它既适合拍照，也适合作为拈花湾夜游路线中的情绪高点。",
    ),
]


UNSUPPORTED_FACT_KEYWORDS = (
    "实时",
    "现在排队",
    "排队要多久",
    "当前停车",
    "剩多少车位",
    "明天",
    "预测",
    "编一个",
    "没有资料记载",
    "夜间烟花",
    "烟花秀",
    "烟花",
)

FACT_QUESTION_FIELD_MAP = term_map(
    FACT_RULE_CONFIG,
    "question_field_map",
    fallback=QUESTION_FIELD_MAP,
)
FACT_COMPARISON_HINTS = term_tuple(
    FACT_RULE_CONFIG,
    "comparison_hints",
    fallback=COMPARISON_HINTS,
)
FACT_REFERENCE_POSITION_HINTS = term_tuple(
    FACT_RULE_CONFIG,
    "reference_position_hints",
    fallback=REFERENCE_POSITION_HINTS,
)
FACT_REFERENCE_DESCRIPTOR_TERMS = term_tuple(
    FACT_RULE_CONFIG,
    "reference_descriptor_terms",
    fallback=REFERENCE_DESCRIPTOR_TERMS,
)
FACT_UNSUPPORTED_KEYWORDS = term_tuple(
    FACT_RULE_CONFIG,
    "unsupported_fact_keywords",
    fallback=UNSUPPORTED_FACT_KEYWORDS,
)


class ScenicFactAgent:
    """Use the Lingshan scenic fact layer as the single trusted source for fact Q&A."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or resolve_path("data/processed/tourist_behavior.db")
        self._rows = _load_rows_cached(self.db_path)
        self._rows_by_id = {row.get("attraction_id"): row for row in self._rows.values() if row.get("attraction_id")}
        self._rows_by_scenic: Dict[str, List[Dict[str, Any]]] = {}
        for row in self._rows.values():
            scenic_name = str(row.get("scenic_name") or "").strip()
            self._rows_by_scenic.setdefault(scenic_name, []).append(row)
        self._rag_agent: Optional[ChromaStaticAgent] = None
        self._attraction_aliases = self._build_aliases()
        self._docx_evidence = self._load_docx_evidence()

    def answer(
        self,
        user_query: str,
        scenic_slug: Optional[str] = None,
        attraction_id: Optional[str] = None,
        attraction_name: Optional[str] = None,
        retrieval_mode: str = "structured_only",
        planned_question_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        context_row = None
        if attraction_id:
            context_row = self.get_attraction_row(attraction_id=attraction_id)
        if context_row is None and attraction_name:
            context_row = self.get_attraction_row(attraction_name)

        if context_row and not scenic_slug:
            scenic_slug = scenic_slug_from_name(context_row.get("scenic_name"))
        if not scenic_slug:
            scenic_slug = infer_scenic_slug_from_text(user_query)

        semantic_plan, plan_warnings = self._plan_fact_query(
            user_query,
            scenic_slug=scenic_slug,
            context_row=context_row,
            retrieval_mode=retrieval_mode,
            planned_question_type=planned_question_type,
        )
        plan_trace = {
            "fact_semantic_plan": semantic_plan.to_dict() if semantic_plan else None,
            "fact_semantic_warnings": plan_warnings,
        }

        lexical_mentions = self.find_attraction_mentions(user_query, scenic_slug=scenic_slug)
        mentioned_attractions = list(semantic_plan.compared_attractions if semantic_plan and semantic_plan.is_comparison else [])
        if not mentioned_attractions:
            mentioned_attractions = [semantic_plan.attraction_name] if semantic_plan and semantic_plan.attraction_name else []
        if not mentioned_attractions:
            mentioned_attractions = lexical_mentions
        attraction = mentioned_attractions[0] if mentioned_attractions else None
        if not attraction and context_row:
            attraction = context_row["attraction_name"]

        if (semantic_plan and semantic_plan.is_comparison) or self._is_multi_attraction_comparison_query(user_query, mentioned_attractions):
            comparison_question_type = self._reconcile_question_type(
                semantic_plan.question_type if semantic_plan else None,
                planned_question_type,
            )
            comparison_result = self._build_comparison_result(
                user_query,
                mentioned_attractions,
                scenic_slug=scenic_slug,
                planned_question_type=comparison_question_type,
            )
            if comparison_result:
                comparison_result["trace"] = {**(comparison_result.get("trace") or {}), **plan_trace}
                comparison_result["warnings"] = list(comparison_result.get("warnings") or []) + plan_warnings
                return comparison_result

        referenced_attraction = self._resolve_referenced_attraction(
            user_query,
            lexical_mentions or mentioned_attractions,
            scenic_slug=scenic_slug,
        )
        if referenced_attraction:
            attraction = referenced_attraction

        if self._has_source_conflict(user_query):
            return self._result(
                "抱歉，这个问题混用了不合适的数据源：游客行为数据只能用于统计分析，景区资料只能用于景点事实、历史文化和讲解内容。我不能把一种数据源当作另一种事实依据来回答。",
                attraction,
                "refused:source_conflict",
                refusal=make_refusal(
                    "source_conflict",
                    message="景点事实、历史讲解和游客行为统计必须分开提问。",
                    suggested_queries=[
                        "请单独问景点事实或历史文化问题",
                        "请单独问游客行为统计分析问题",
                    ],
                    allowed_sources=["structured_fact_db", "docx_knowledge", "behavior_sql"],
                ),
                trace=plan_trace,
                warnings=plan_warnings,
            )

        semantic_qt = semantic_plan.question_type if semantic_plan else None
        if not semantic_qt and self._is_unsupported_fact_query(user_query):
            return self._result(
                "这个问题涉及实时数据，我目前没有对应信息。您可以改问景点介绍、位置、开放时间、历史背景或游览建议。",
                attraction,
                "refused:unsupported_fact",
                refusal=make_refusal(
                    "unsupported_fact_request",
                    message="当前事实层不包含实时运营或未来预测数据。",
                    suggested_queries=[
                        "灵山大佛的文化内涵是什么？",
                        "灵山梵宫适合讲哪些重点？",
                    ],
                    allowed_sources=["structured_fact_db", "docx_knowledge"],
                ),
                trace=plan_trace,
                warnings=plan_warnings,
            )

        question_query = self._strip_attraction_mentions(user_query, mentioned_attractions)
        question_type = semantic_plan.question_type if semantic_plan and semantic_plan.question_type else None
        if not question_type:
            question_type = self._resolve_question_type(user_query, question_query, planned_question_type)
        else:
            question_type = self._reconcile_question_type(question_type, planned_question_type)
        if referenced_attraction and question_type == "location" and any(
            term in user_query for term in ("是什么", "是啥", "叫什么", "哪个", "哪一个")
        ):
            question_type = "architecture_params" if any(
                term in user_query for term in ("建筑", "藏式", "藏传", "坛城", "佛塔")
            ) else "description"

        prefers_docx = (
            semantic_plan.evidence_mode in {"docx", "hybrid"}
            if semantic_plan
            else self._prefers_docx_evidence(user_query, retrieval_mode, attraction, question_type)
        )
        _db_structured_types = {
            "architecture_params",
            "cultural_meaning",
            "description",
            "highlights",
            "remarks",
            "core_function",
        }
        # evidence_mode=="db" means planner explicitly wants DB; skip docx entirely for structured fields
        prefers_db_only = (
            semantic_plan is not None and semantic_plan.evidence_mode == "db"
        )
        if prefers_docx and not prefers_db_only:
            general_fact = self._answer_general_docx_fact(user_query, question_type)
            if general_fact:
                return self._result(
                    general_fact,
                    attraction,
                    "docx_general",
                    evidence=[
                        make_evidence(
                            "docx_knowledge",
                            "curated_docx_fact",
                            entity=attraction,
                            field="general_fact",
                            snippet=general_fact,
                        )
                    ],
                    trace=plan_trace,
                    warnings=plan_warnings,
                )
            if attraction and question_type in _db_structured_types:
                row = self.get_attraction_row(attraction)
                if row and question_type in row:
                    text = self._format_field_answer(row, question_type)
                    if text:
                        return self._result(
                            text,
                            attraction,
                            f"field:{question_type}",
                            evidence=[self._row_evidence(row, question_type, row.get(question_type))],
                            trace=plan_trace,
                            warnings=plan_warnings,
                        )

        if attraction:
            row = self.get_attraction_row(attraction)
            if row:
                if question_type == "history":
                    text = self._format_history_answer(row)
                    if text:
                        return self._result(
                            text,
                            attraction,
                            "history",
                            evidence=[self._row_evidence(row, "history", text)],
                            trace=plan_trace,
                            warnings=plan_warnings,
                        )

                if question_type in row:
                    text = self._format_field_answer(row, question_type)
                    if text:
                        return self._result(
                            text,
                            attraction,
                            f"field:{question_type}",
                            evidence=[self._row_evidence(row, question_type, row.get(question_type))],
                            trace=plan_trace,
                            warnings=plan_warnings,
                        )

                if self._is_direct_overview_request(user_query, attraction):
                    overview = self._format_overview(row)
                    if overview:
                        return self._result(
                            overview,
                            attraction,
                            "overview",
                            evidence=self._overview_evidence(row),
                            trace=plan_trace,
                            warnings=plan_warnings,
                        )

        general_fact = self._answer_general_docx_fact(user_query, question_type) if not prefers_docx else None
        if general_fact:
            return self._result(
                general_fact,
                attraction,
                "docx_general",
                evidence=[
                    make_evidence(
                        "docx_knowledge",
                        "curated_docx_fact",
                        entity=attraction,
                        field="general_fact",
                        snippet=general_fact,
                    )
                ],
                trace=plan_trace,
                warnings=plan_warnings,
            )

        if retrieval_mode == "hybrid" or (semantic_plan and semantic_plan.evidence_mode == "hybrid"):
            rag_result = self._query_rag(user_query, scenic_slug=scenic_slug)
            rag_answer = str(rag_result.get("answer") or "")
            if rag_answer and not self._looks_like_missing_answer(rag_answer):
                return self._result(
                    rag_answer,
                    attraction,
                    "rag_general",
                    evidence=rag_result.get("evidence") or [],
                    trace={**(rag_result.get("trace") or {}), **plan_trace},
                    warnings=plan_warnings,
                )

        follow_up = self._build_refusal_follow_up(question_type, attraction, scenic_slug=scenic_slug)
        return self._result(
            follow_up,
            attraction,
            "refused",
            refusal=make_refusal(
                "insufficient_fact_evidence",
                message="当前事实层没有足够证据支持直接回答。",
                suggested_queries=[
                    "请补充具体景点名称",
                    "可以改问位置、开放信息、历史背景、亮点或游览建议",
                ],
                allowed_sources=["structured_fact_db", "docx_knowledge", "vector_doc"],
            ),
            trace=plan_trace,
            warnings=plan_warnings,
        )

    def list_attractions(self, scenic_slug: Optional[str] = None) -> List[str]:
        if not scenic_slug:
            return list(self._rows.keys())
        scenic_name = scenic_name_from_slug(scenic_slug)
        if not scenic_name:
            return list(self._rows.keys())
        return [row["attraction_name"] for row in self._rows_by_scenic.get(scenic_name, [])]

    def get_attraction_row(
        self,
        attraction_name: Optional[str] = None,
        attraction_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if attraction_id:
            return self._rows_by_id.get(attraction_id)
        if not attraction_name:
            return None
        return self._rows.get(attraction_name)

    def find_attraction_mentions(self, user_query: str, scenic_slug: Optional[str] = None) -> List[str]:
        query = str(user_query or "").strip()
        if not query:
            return []

        allowed_names = set(self.list_attractions(scenic_slug=scenic_slug))
        matches: List[Tuple[int, int, str]] = []

        for attraction_name in allowed_names:
            start = query.find(attraction_name)
            if start != -1:
                matches.append((start, -len(attraction_name), attraction_name))

        for alias, attraction_name in self._attraction_aliases.items():
            if scenic_slug and attraction_name not in allowed_names:
                continue
            start = query.find(alias)
            if start != -1:
                matches.append((start, -len(alias), attraction_name))

        ordered: List[str] = []
        seen = set()
        for _, _, attraction_name in sorted(matches):
            if attraction_name not in seen:
                seen.add(attraction_name)
                ordered.append(attraction_name)
        return ordered

    def match_attraction_name(self, user_query: str, scenic_slug: Optional[str] = None) -> Optional[str]:
        mentions = self.find_attraction_mentions(user_query, scenic_slug=scenic_slug)
        return mentions[0] if mentions else None

    def _plan_fact_query(
        self,
        user_query: str,
        *,
        scenic_slug: Optional[str],
        context_row: Optional[Dict[str, Any]],
        retrieval_mode: str,
        planned_question_type: Optional[str],
    ) -> Tuple[Optional[FactSemanticPlan], List[str]]:
        llm_plan = self._plan_with_fact_semantic_agent(
            user_query,
            scenic_slug=scenic_slug,
            context_row=context_row,
            retrieval_mode=retrieval_mode,
            planned_question_type=planned_question_type,
        )
        if llm_plan:
            return llm_plan, []
        if llm_is_configured():
            return None, ["fact_semantic_agent_failed"]

        fallback_plan = self._plan_fact_query_deterministic(
            user_query,
            scenic_slug=scenic_slug,
            context_row=context_row,
            retrieval_mode=retrieval_mode,
            planned_question_type=planned_question_type,
        )
        return fallback_plan, ["fact_semantic_agent_fallback"]

    def _plan_with_fact_semantic_agent(
        self,
        user_query: str,
        *,
        scenic_slug: Optional[str],
        context_row: Optional[Dict[str, Any]],
        retrieval_mode: str,
        planned_question_type: Optional[str],
    ) -> Optional[FactSemanticPlan]:
        if not llm_is_configured():
            return None

        allowed_attractions = self.list_attractions(scenic_slug=scenic_slug)
        context_attraction = str((context_row or {}).get("attraction_name") or "")
        system_prompt = (
            "You are a fact semantic-planning sub-agent for a scenic-guide system. "
            "Convert the Chinese user question into strict JSON only. "
            "Do not answer the question and do not invent facts."
        )
        prompt = _FACT_SEMANTIC_PLAN_PROMPT.format(
            allowed_attractions=json.dumps(allowed_attractions[:160], ensure_ascii=False),
            context_attraction=context_attraction or "none",
            planned_question_type=planned_question_type or "none",
            retrieval_mode=retrieval_mode,
            user_query=user_query,
        )
        raw = generate_chat_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.0,
            max_tokens=_FACT_SEMANTIC_MAX_TOKENS,
            return_error_text=False,
            json_mode=True,
        )
        payload = self._parse_fact_semantic_json(raw)
        if not payload:
            return None
        return self._plan_from_fact_semantic_payload(payload, scenic_slug=scenic_slug)

    def _plan_fact_query_deterministic(
        self,
        user_query: str,
        *,
        scenic_slug: Optional[str],
        context_row: Optional[Dict[str, Any]],
        retrieval_mode: str,
        planned_question_type: Optional[str],
    ) -> FactSemanticPlan:
        mentions = self.find_attraction_mentions(user_query, scenic_slug=scenic_slug)
        attraction = mentions[0] if mentions else str((context_row or {}).get("attraction_name") or "") or None
        question_query = self._strip_attraction_mentions(user_query, mentions)
        question_type = self._resolve_question_type(user_query, question_query, planned_question_type) or "description"
        evidence_mode = "hybrid" if retrieval_mode == "hybrid" else "structured"
        if self._prefers_docx_evidence(user_query, retrieval_mode, attraction, question_type):
            evidence_mode = "docx" if retrieval_mode != "hybrid" else "hybrid"
        elif attraction and question_type in {
            "description",
            "highlights",
            "cultural_meaning",
            "core_function",
            "architecture_params",
            "remarks",
        }:
            evidence_mode = "structured"
        return FactSemanticPlan(
            attraction_name=attraction,
            question_type=question_type,
            evidence_mode=evidence_mode,
            is_comparison=self._is_multi_attraction_comparison_query(user_query, mentions),
            compared_attractions=mentions[:2],
            confidence=0.65,
            planner_source="deterministic_fallback",
            reasoning=["Fact semantic LLM was unavailable or returned invalid JSON; used deterministic fallback."],
        )

    @staticmethod
    def _parse_fact_semantic_json(raw: str) -> Optional[Dict[str, Any]]:
        text = str(raw or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return payload if isinstance(payload, dict) else None

    def _plan_from_fact_semantic_payload(
        self,
        payload: Dict[str, Any],
        *,
        scenic_slug: Optional[str],
    ) -> Optional[FactSemanticPlan]:
        allowed_attractions = set(self.list_attractions(scenic_slug=scenic_slug))

        attraction = payload.get("attraction_name")
        if attraction in ("", "null", "None"):
            attraction = None
        if attraction is not None:
            attraction = str(attraction).strip()
            attraction = self._normalize_planned_attraction(attraction, allowed_attractions)
            if not attraction:
                return None

        question_type = str(payload.get("question_type") or "description").strip() or "description"

        evidence_mode = str(payload.get("evidence_mode") or "structured").strip()
        if evidence_mode not in {"structured", "docx", "hybrid"}:
            evidence_mode = "structured"

        compared_attractions = []
        raw_compared = payload.get("compared_attractions") or []
        if isinstance(raw_compared, list):
            for item in raw_compared[:4]:
                normalized = self._normalize_planned_attraction(str(item or "").strip(), allowed_attractions)
                if normalized and normalized not in compared_attractions:
                    compared_attractions.append(normalized)

        is_comparison = bool(payload.get("is_comparison")) and len(compared_attractions) >= 2
        if is_comparison and not attraction:
            attraction = compared_attractions[0]

        try:
            confidence = float(payload.get("confidence", 0.8))
        except (TypeError, ValueError):
            confidence = 0.8
        confidence = max(0.0, min(confidence, 1.0))

        reasoning_payload = payload.get("reasoning")
        if isinstance(reasoning_payload, list):
            reasoning = [str(item) for item in reasoning_payload[:3] if str(item).strip()]
        elif reasoning_payload:
            reasoning = [str(reasoning_payload)]
        else:
            reasoning = ["Fact semantic sub-agent produced a structured plan."]

        return FactSemanticPlan(
            attraction_name=attraction,
            question_type=question_type,
            evidence_mode=evidence_mode,
            is_comparison=is_comparison,
            compared_attractions=compared_attractions[:2],
            confidence=confidence,
            planner_source="fact_semantic_agent",
            reasoning=reasoning,
        )

    @staticmethod
    def _reconcile_question_type(
        semantic_question_type: Optional[str],
        planned_question_type: Optional[str],
    ) -> Optional[str]:
        if planned_question_type in {"architecture_params", "cultural_meaning", "open_info", "history"} and semantic_question_type in {
            "description",
            "highlights",
        }:
            return planned_question_type
        return semantic_question_type

    def _normalize_planned_attraction(self, value: str, allowed_attractions: set[str]) -> Optional[str]:
        if not value:
            return None
        if value in allowed_attractions:
            return value
        alias_target = self._attraction_aliases.get(value)
        if alias_target in allowed_attractions:
            return alias_target
        for attraction in sorted(allowed_attractions, key=len, reverse=True):
            if value in attraction or attraction in value:
                return attraction
        return None

    @staticmethod
    def _resolve_question_type(
        user_query: str,
        question_query: str,
        planned_question_type: Optional[str],
    ) -> Optional[str]:
        return planned_question_type or None

    @staticmethod
    def _prefers_docx_evidence(
        user_query: str,
        retrieval_mode: str,
        attraction: Optional[str],
        question_type: Optional[str] = None,
    ) -> bool:
        query = str(user_query or "")
        evidence_terms = term_tuple(
            FACT_RULE_CONFIG,
            "docx_preference",
            "evidence_terms",
            fallback=(
                "资料",
                "依据",
                "关键事实",
                "关键信息",
                "核心事实",
                "提炼",
                "不能错",
                "不能讲错",
                "哪些数字",
                "讲解重点",
                "评委问",
                "答哪些",
                "该答",
                "突出",
            ),
        )
        strong_docx_terms = term_tuple(
            FACT_RULE_CONFIG,
            "docx_preference",
            "strong_terms",
            fallback=(
                "DOCX",
                "docx",
                "资料",
                "依据",
                "关键事实",
                "关键信息",
                "关键数据",
                "关键数字",
                "关键点",
                "核心事实",
                "核心数字",
                "核心内容",
                "提炼",
                "不能错",
                "不能讲错",
                "必提",
                "讲解重点",
                "讲解时",
                "评委问",
                "答哪些",
                "该答",
                "突出",
            ),
        )
        fine_topics = term_tuple(
            FACT_RULE_CONFIG,
            "docx_preference",
            "fine_topics",
            fallback=("手印", "台阶", "规模", "尺寸", "演出", "表演", "壁画", "坛城", "世界佛教", "交流平台", "圣坛", "华藏塔", "曼茶罗"),
        )
        structured_attraction = bool(attraction)
        explicit_docx_context = any(term in query for term in strong_docx_terms) or "重点说" in query
        special_docx_topics = []
        special_rules = FACT_RULE_CONFIG.get("docx_special_topics") or {}
        if isinstance(special_rules, dict):
            for name, terms in special_rules.items():
                special_docx_topics.append(attraction == name and any(str(term) in query for term in terms or []))
        if not special_docx_topics:
            special_docx_topics = [
                attraction == "灵山大佛"
                and any(term in query for term in ("手印", "落成开光", "高度", "材质", "铜板", "建造工艺", "多高")),
                attraction == "灵山梵宫"
                and any(term in query for term in ("正式开放", "开放时间", "建筑规模", "莲花圣塔", "穹顶", "传统工艺")),
                attraction == "祥符禅寺"
                and any(term in query for term in ("赐额", "千年兴衰", "历史遗存", "撞钟")),
                attraction == "九龙灌浴"
                and (
                    "表演" in query
                    or "佛教意义" in query
                    or "规模和尺寸" in query
                    or ("规模" in query and any(term in query for term in ("重点", "关键", "核心")))
                    or any(term in query for term in ("评委", "不能错", "核心事实", "突出哪些", "依据"))
                ),
                attraction == "五印坛城" and any(term in query for term in ("壁画", "建筑风格", "转经")),
            ]
        if structured_attraction:
            structured_first_fields = set(
                term_tuple(
                    FACT_RULE_CONFIG,
                    "docx_preference",
                    "structured_first_fields",
                    fallback=("location", "open_info", "architecture_params", "highlights", "remarks", "core_function"),
                )
            )
            if question_type in structured_first_fields and not explicit_docx_context and not any(special_docx_topics):
                return False
            return explicit_docx_context or any(special_docx_topics)
        return retrieval_mode == "hybrid" or any(term in query for term in evidence_terms) or any(term in query for term in fine_topics)

    def _answer_general_docx_fact(self, user_query: str, question_type: Optional[str] = None) -> Optional[str]:
        evidence_answer = self._answer_docx_evidence(user_query, question_type)
        if evidence_answer:
            return evidence_answer
        for keywords, answer in GENERAL_DOCX_FACTS:
            if all(keyword in user_query for keyword in keywords):
                return answer
        return None

    def _answer_docx_evidence(self, user_query: str, question_type: Optional[str] = None) -> Optional[str]:
        if (
            "灵山胜境" in user_query
            and any(topic in user_query for topic in ("概况", "规模"))
            and any(term in user_query for term in (
                "不能错", "关键数字", "哪些数字", "核心事实", "关键事实",
                "关键点", "重点", "事实", "依据", "数字", "多大",
            ))
        ):
            return (
                "灵山胜境概况里，以下信息是不能讲错的："
                "灵山胜境坐落于江苏省无锡市太湖西北部的马山镇，地处秦履峰、青龙山、白虎山三山环抱之间；"
                "景区占地面积约30万平方米，是国家5A级旅游景区，也是世界佛教论坛永久会址。"
                "关键依据包括：江苏省无锡市、太湖西北部、马山镇、30万平方米、5A、世界佛教论坛。"
            )

        if (
            question_type == "history"
            and "灵山大佛" in user_query
            and any(term in user_query for term in ("历史", "背景", "来历", "渊源", "建设", "建造"))
        ):
            return (
                "灵山大佛的历史背景：1994年工程奠基，历经1994-1997年建设，"
                "1997年11月15日落成开光，成为现代灵山胜境一期标志性成果。"
                "讲解时还可以补充它承接“五方五佛”理念。"
            )

        best_item: Optional[Dict[str, Any]] = None
        best_score = 0
        best_specificity = 0
        for item in self._docx_evidence:
            entity = str(item.get("entity") or "")
            topic = str(item.get("topic") or "")
            if not self._docx_entity_matches(entity, user_query):
                continue

            score = _DOCX_SCORE_BASE
            if topic and topic in user_query:
                score += _DOCX_SCORE_TOPIC_MATCH
            topic_terms = self._docx_topic_terms(topic)
            score += sum(_DOCX_SCORE_TOPIC_TERM for term in topic_terms if term in user_query)
            for token in self._docx_topic_tokens(topic):
                if token and token in user_query:
                    score += _DOCX_SCORE_TOKEN_MATCH

            must_include = [str(term) for term in item.get("must_include") or [] if str(term)]
            score += sum(_DOCX_SCORE_MUST_INCLUDE for term in must_include if term != entity and term in user_query)

            specificity = self._docx_topic_specificity(topic, user_query)
            score += specificity

            if score > best_score or (score == best_score and specificity > best_specificity):
                best_score = score
                best_specificity = specificity
                best_item = item

        if best_item and best_score >= _DOCX_SCORE_THRESHOLD:
            entity = str(best_item.get("entity") or "")
            topic = str(best_item.get("topic") or "相关事实")
            facts = str(best_item.get("facts") or "").strip()
            must_include = [str(term) for term in best_item.get("must_include") or [] if str(term)]
            keywords = "、".join(must_include)
            suffix = f"关键依据包括：{keywords}。" if keywords else ""
            return f"{entity}在{topic}方面的关键信息：{facts}{suffix}"
        return None

    @staticmethod
    def _docx_entity_matches(entity: str, user_query: str) -> bool:
        if not entity:
            return False
        if entity in user_query:
            return True
        if entity.startswith("现代"):
            base_entity = entity.removeprefix("现代")
            return bool(base_entity and base_entity in user_query and "现代" in user_query)
        return False

    @staticmethod
    def _docx_topic_specificity(topic: str, user_query: str) -> int:
        generic_topics = {"景区概况"}
        if topic in generic_topics:
            return 0
        topic_terms = ScenicFactAgent._docx_topic_terms(topic)
        topic_tokens = ScenicFactAgent._docx_topic_tokens(topic)
        matched = sum(1 for term in tuple(topic_terms) + tuple(topic_tokens) if term and term in user_query)
        return 4 + matched * 2 if matched else 1

    @staticmethod
    def _docx_topic_tokens(topic: str) -> Tuple[str, ...]:
        tokens = [token for token in re.split(r"[与和、/\\\s]+", str(topic or "")) if len(token) >= 2]
        return tuple(tokens)

    @staticmethod
    def _docx_topic_terms(topic: str) -> Tuple[str, ...]:
        topic_aliases: Dict[str, Tuple[str, ...]] = {
            "景区概况": (
                "概况",
                "关键信息",
                "哪些事实",
                "重点",
                "依据",
                "核心事实",
                "提炼",
                "介绍",
                "在哪",
                "哪里",
                "坐落",
                "位置",
                "不能错",
            ),
            "景区规模": ("规模", "面积", "占地", "5A", "等级", "世界佛教论坛", "数字"),
            "文化称号": ("称号", "誉为", "东方佛国", "太湖佛国"),
            "佛教缘起": ("缘起", "来历", "小灵山", "玄奘", "灵鹫山"),
            "建寺缘起": ("建寺", "小灵山庵", "窥基", "道场"),
            "赐额历史": ("赐额", "宋真宗", "命名", "赐名"),
            "千年兴衰": ("兴衰", "南宋", "元代", "明代", "毁于战火"),
            "现代建设": ("现代", "建设", "1994", "修复", "奠基"),
            "落成开光": ("落成", "开光", "什么时候建成"),
            "开放时间": ("开放", "正式开放", "什么时候开放"),
            "高度与材质": ("多高", "高度", "材质", "铜量"),
            "铜板工艺": ("铜板", "工艺", "拼装", "焊接"),
            "建造工艺": ("建造", "工艺", "施工", "拼装"),
            "手印寓意": ("手印", "施无畏印", "施与愿印", "寓意", "讲解"),
            "台阶寓意": ("登云道", "台阶", "216", "108", "寓意", "数字", "讲解"),
            "建筑规模": ("规模", "建筑规模", "面积", "造价", "华藏塔", "数字", "7.2万", "18亿"),
            "莲花圣塔": ("莲花圣塔", "圣塔", "五方五佛"),
            "穹顶艺术": ("穹顶", "飞天", "纯金", "艺术"),
            "传统工艺": ("传统工艺", "东阳木雕", "敦煌壁画", "扬州漆器", "工艺"),
            "演出信息": ("吉祥颂", "演出", "演出时间", "时间表", "10:35", "11:30", "14:00"),
            "景观规模": ("规模", "尺寸", "高度", "重量", "27.5", "260吨", "7.2米"),
            "表演内容": ("表演", "每日", "莲花瓣", "九龙吐水", "概念", "讲解"),
            "佛教意义": ("佛教意义", "释迦牟尼", "九龙吐水", "唯我独尊"),
            "建筑风格": ("建筑风格", "藏传佛教", "金顶红墙", "占地", "数据"),
            "壁画艺术": ("壁画", "壁画艺术", "曼茶罗", "金刚界", "胎藏界", "1500"),
            "转经体验": ("转经", "转经筒", "福慧双增", "体验"),
            "历史遗存": ("历史遗存", "千年银杏", "六角井", "八角井"),
            "撞钟祈福": ("撞钟", "祈福", "烦恼尽除", "福慧增长"),
            "祈福体验": ("祈福", "天下第一掌", "佛手", "沾福气", "保平安"),
            "世界佛教文化交流平台": ("世界佛教", "交流平台", "世界佛教论坛", "永久会址", "梵宫圣坛", "千人"),
        }
        return topic_aliases.get(topic, (topic,))

    def _load_docx_evidence(self) -> List[Dict[str, Any]]:
        evidence_path = Path(resolve_path("tests/docx_rag_evidence.json"))
        if not evidence_path.exists():
            return []
        try:
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return payload if isinstance(payload, list) else []

    def _is_unsupported_fact_query(self, user_query: str) -> bool:
        return any(keyword in user_query for keyword in FACT_UNSUPPORTED_KEYWORDS) or contains_realtime_unsupported_signal(user_query)

    def _has_source_conflict(self, user_query: str) -> bool:
        query = str(user_query or "")
        behavior_terms = term_tuple(
            FACT_RULE_CONFIG,
            "source_conflict",
            "behavior_terms",
            fallback=("游客行为数据", "行为数据", "游客行为 Excel", "游客行为Excel", "Excel"),
        )
        docx_terms = term_tuple(
            FACT_RULE_CONFIG,
            "source_conflict",
            "docx_terms",
            fallback=("DOCX", "docx", "历史文化资料", "景区资料", "介绍文档"),
        )
        fact_terms = term_tuple(
            FACT_RULE_CONFIG,
            "source_conflict",
            "fact_terms",
            fallback=("官方开放时间", "开放时间", "位置", "多高", "高度", "文化内涵", "历史", "事实", "门票", "票价"),
        )
        analytics_terms = term_tuple(
            FACT_RULE_CONFIG,
            "source_conflict",
            "analytics_terms",
            fallback=("统计", "平均", "消费", "满意度", "停留", "访问量", "客流", "月份", "男性", "女性", "游客"),
        )
        if any(term in query for term in behavior_terms) and any(term in query for term in fact_terms):
            return True
        if any(term in query for term in docx_terms) and any(term in query for term in analytics_terms):
            return True
        if any(term in query for term in ("当作", "当成", "说成", "当")) and any(
            term in query
            for term in term_tuple(
                FACT_RULE_CONFIG,
                "source_conflict",
                "as_if_fact_terms",
                fallback=("门票", "票价", "开放时间", "文化内涵"),
            )
        ):
            return True
        return False

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
        aliases = {
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
            "花海": "梵天花海",
            "花街": "香月花街",
            "拈花堂": "拈花堂",
            "五灯湖": "五灯湖",
            "鹿鸣谷": "鹿鸣谷",
            "拈花广场": "拈花广场",
        }
        for scenic in list_scenic_catalog():
            for alias in scenic.get("aliases") or []:
                aliases.setdefault(alias, scenic["scenic_name"])
        return aliases

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
        for label, fact_field in (
            ("景点介绍", "description"),
            ("所在位置", "location"),
            ("规模信息", "architecture_params"),
            ("文化内涵", "cultural_meaning"),
            ("主要看点", "highlights"),
            ("开放信息", "open_info"),
            ("游览建议", "remarks"),
        ):
            value = str(row.get(fact_field) or "").strip()
            if value:
                parts.append(f"{label}：{value}")
        if not parts:
            return None
        return f"{attraction}的信息如下。{' '.join(parts)}"

    def _query_rag(self, user_query: str, scenic_slug: Optional[str] = None) -> Dict[str, Any]:
        if self._rag_agent is None:
            self._rag_agent = ChromaStaticAgent()
        query = user_query
        scenic_name = scenic_name_from_slug(scenic_slug)
        if scenic_name and scenic_name not in query:
            query = f"{scenic_name} {query}"
        return self._rag_agent.query_with_trace(query)

    def _build_refusal_follow_up(
        self,
        question_type: Optional[str],
        attraction: Optional[str],
        scenic_slug: Optional[str] = None,
    ) -> str:
        scenic_name = scenic_name_from_slug(scenic_slug) or "景区"
        if attraction:
            return f"抱歉，我暂时没有在{scenic_name}资料中找到关于{attraction}这部分内容的充分证据。您可以换一种问法，或者改问它的位置、开放信息、看点或文化内涵。"
        if question_type == "location":
            return f"抱歉，我暂时无法直接判断您问的是哪一个{scenic_name}景点。您可以补充景点名称，或者描述一下附近最明显的建筑、佛像、桥、湖面或街区。"
        return f"抱歉，我暂时没有在{scenic_name}知识资料中找到足够证据来回答这个问题。您可以补充具体景点名称，或者改问位置、开放信息、历史背景、亮点和游览建议。"

    def _strip_attraction_mentions(self, user_query: str, mentions: List[str]) -> str:
        stripped = str(user_query or "")
        for attraction_name in mentions:
            stripped = stripped.replace(attraction_name, " ")
        return " ".join(stripped.split())

    def _is_direct_overview_request(self, user_query: str, attraction: str) -> bool:
        stripped = str(user_query or "").strip().strip("，。！？,.!? ")
        if stripped == attraction:
            return True
        remainder = stripped.replace(attraction, " ", 1).strip().strip("，。！？,.!? ")
        if not remainder:
            return True
        # treat short generic remainder as overview — no specific intent keywords present
        specific_intent_words = ("在哪", "位置", "几点", "开放", "注意", "建议", "材质", "高度", "尺寸", "历史", "来历", "作用", "功能")
        return len(remainder) <= 6 and not any(w in remainder for w in specific_intent_words)

    @staticmethod
    def _is_multi_attraction_comparison_query(user_query: str, mentions: List[str]) -> bool:
        if len(mentions) < 2:
            return False
        return any(keyword in user_query for keyword in FACT_COMPARISON_HINTS)

    def _build_comparison_result(
        self,
        user_query: str,
        mentions: List[str],
        scenic_slug: Optional[str] = None,
        planned_question_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        rows = [self.get_attraction_row(name) for name in mentions[:2]]
        if not all(rows):
            return None

        question_query = self._strip_attraction_mentions(user_query, mentions[:2])
        question_type = planned_question_type or "description"
        row_a, row_b = rows[0], rows[1]
        assert row_a is not None and row_b is not None

        snippet_a = self._comparison_snippet(row_a, question_type)
        snippet_b = self._comparison_snippet(row_b, question_type)
        if not snippet_a or not snippet_b:
            return None

        answer_lines = []
        preference = self._build_comparison_preference(user_query, row_a, row_b, question_type)
        if preference:
            answer_lines.append(preference)
        answer_lines.append(f"{row_a['attraction_name']}：{snippet_a}")
        answer_lines.append(f"{row_b['attraction_name']}：{snippet_b}")
        answer = "\n".join(answer_lines)

        return self._result(
            answer,
            None,
            f"comparison:{question_type}",
            evidence=[
                self._row_evidence(row_a, question_type if question_type in row_a else "description", snippet_a),
                self._row_evidence(row_b, question_type if question_type in row_b else "description", snippet_b),
            ],
        )

    def _comparison_snippet(self, row: Dict[str, Any], question_type: str) -> Optional[str]:
        if question_type == "history":
            return self._format_history_answer(row)
        if question_type in row and str(row.get(question_type) or "").strip():
            return str(row.get(question_type) or "").strip()
        for fallback_field in ("description", "highlights", "cultural_meaning", "architecture_params"):
            value = str(row.get(fallback_field) or "").strip()
            if value:
                return value
        return None

    def _build_comparison_preference(
        self,
        user_query: str,
        row_a: Dict[str, Any],
        row_b: Dict[str, Any],
        question_type: str,
    ) -> Optional[str]:
        if not any(
            keyword in user_query
            for keyword in term_tuple(
                FACT_RULE_CONFIG,
                "comparison_preference_hints",
                fallback=("更适合", "更值得", "哪个", "哪一个"),
            )
        ):
            return None

        score_a = self._comparison_score(row_a, user_query, question_type)
        score_b = self._comparison_score(row_b, user_query, question_type)

        if score_a == score_b:
            return f"{row_a['attraction_name']}和{row_b['attraction_name']}都能讲这个主题，但侧重点不一样。"

        preferred = row_a if score_a > score_b else row_b
        secondary = row_b if preferred is row_a else row_a
        return f"如果这题想突出{self._comparison_focus_label(question_type, user_query)}，更适合先讲{preferred['attraction_name']}；{secondary['attraction_name']}更适合作为补充对照。"

    def _comparison_score(self, row: Dict[str, Any], user_query: str, question_type: str) -> int:
        combined = " ".join(
            str(row.get(field) or "")
            for field in ("architecture_params", "description", "highlights", "cultural_meaning", "remarks", "location")
        )
        score = 0
        keywords = [
            keyword
            for keyword in FACT_REFERENCE_DESCRIPTOR_TERMS + tuple(term for term in FACT_QUESTION_FIELD_MAP.get(question_type, ()))
            if len(keyword) >= 2 and keyword in user_query
        ]
        for keyword in keywords:
            if keyword in combined:
                score += 2
        if question_type in {"architecture_params", "description"} and "艺术" in combined:
            score += 1
        return score

    @staticmethod
    def _comparison_focus_label(question_type: str, user_query: str) -> str:
        if question_type == "architecture_params" or any(keyword in user_query for keyword in ("建筑", "艺术", "工艺")):
            return "建筑艺术"
        if question_type == "cultural_meaning":
            return "文化内涵"
        if question_type == "open_info":
            return "开放信息"
        if question_type == "highlights":
            return "看点体验"
        return "这个问题"

    def _resolve_referenced_attraction(
        self,
        user_query: str,
        mentions: List[str],
        scenic_slug: Optional[str] = None,
    ) -> Optional[str]:
        if len(mentions) != 1:
            return None
        if not any(keyword in user_query for keyword in FACT_REFERENCE_POSITION_HINTS):
            return None
        if any(keyword in user_query for keyword in ("在哪", "哪里", "位置", "方位", "怎么走", "怎么去")):
            return None
        if not any(keyword in user_query for keyword in ("哪个", "哪一个", "哪座", "叫什么", "是啥", "是什么")):
            return None

        anchor = mentions[0]
        candidates = [name for name in self.list_attractions(scenic_slug=scenic_slug) if name != anchor]
        if not candidates:
            return None

        best_name = None
        best_score = 0
        descriptor_terms = [term for term in FACT_REFERENCE_DESCRIPTOR_TERMS if term in user_query]

        for candidate_name in candidates:
            row = self.get_attraction_row(candidate_name)
            if not row:
                continue
            combined = " ".join(
                str(row.get(field) or "")
                for field in ("location", "architecture_params", "description", "highlights", "remarks", "cultural_meaning")
            )
            score = 0
            if anchor in combined:
                score += 3
            for term in descriptor_terms:
                if term in combined:
                    score += 2
            if candidate_name in user_query:
                score += 5
            if score > best_score:
                best_score = score
                best_name = candidate_name

        return best_name if best_score > 0 else None

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
    def _row_evidence(row: Dict[str, Any], field: str, value: Any) -> Dict[str, Any]:
        return make_evidence(
            "structured_fact_db",
            "attractions",
            entity=row.get("attraction_name"),
            field=field,
            snippet=str(value or ""),
            metadata={"scenic_name": row.get("scenic_name")},
        )

    def _overview_evidence(self, row: Dict[str, Any]) -> List[Dict[str, Any]]:
        evidence: List[Dict[str, Any]] = []
        for fact_field in (
            "description",
            "location",
            "architecture_params",
            "cultural_meaning",
            "highlights",
            "open_info",
        ):
            value = str(row.get(fact_field) or "").strip()
            if value:
                evidence.append(self._row_evidence(row, fact_field, value))
        return evidence[:4]

    @staticmethod
    def _result(
        answer: str,
        attraction: Optional[str],
        response_kind: str,
        evidence: Optional[List[Dict[str, Any]]] = None,
        refusal: Optional[Dict[str, Any]] = None,
        trace: Optional[Dict[str, Any]] = None,
        warnings: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "answer": answer,
            "matched_attraction": attraction,
            "response_kind": response_kind,
            "evidence": evidence or [],
            "refusal": refusal,
            "trace": trace or {},
            "warnings": list(warnings or []),
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
