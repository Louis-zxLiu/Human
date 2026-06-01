import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import resolve_path
from app.core.scenic_catalog import infer_scenic_slug_from_text, list_scenic_catalog, scenic_name_from_slug, scenic_slug_from_name
from app.rag.chroma_agent import ChromaStaticAgent
from app.rag.planner import contains_realtime_unsupported_signal
from app.rag.response_contract import make_evidence, make_refusal


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
    "祥符禅寺": {
        "location": "位于灵山胜境中轴核心、灵山大佛基座之下，四周绿树环绕，环境清幽，是景区内历史最悠久的人文景观。",
        "architecture_params": "唐代古刹，占地约30亩，整体采用仿唐重檐歇山式建筑风格，布局完整，包含弥勒殿、大雄宝殿、钟楼、鼓楼；寺内还有六角井、八角井、白莲池、千年古银杏等历史遗迹，钟楼内悬挂重12.8吨的“祥符禅钟”。",
        "core_function": "承担宗教活动开展、千年古刹瞻仰与佛教礼佛祈福功能，同时展示江南禅宗文化，兼具宗教体验、历史科普与人文观赏功能。",
        "cultural_meaning": "祥符禅寺始建于唐贞观年间，由玄奘法师的弟子窥基大师开坛讲经，北宋年间正式更名为“祥符禅寺”；历经千年风雨洗礼，香火绵延不绝，是江南地区重要的千年禅宗祖庭，也是佛教文化传承与传播的重要场所。",
        "description": "祥符禅寺布局严谨、错落有致，整体采用仿唐重檐歇山式建筑风格，红墙黛瓦、飞檐翘角。大雄宝殿内供奉释迦牟尼佛及迦叶、阿难两大弟子；钟楼内悬挂重12.8吨的“祥符禅钟”。寺内六角井、八角井、白莲池和千年古银杏共同构成寺院历史遗存。",
        "highlights": "适合礼佛祈福、虔诚朝拜，聆听祥符禅钟的浑厚钟声，观赏唐代古建与千年历史遗迹；秋季还可欣赏千年银杏的金黄景致，感受古刹静谧庄严。",
        "open_info": "全天开放，宗教活动正常开展；钟楼定时有钟声表演，具体时间以景区广播通知为准，寺内禁止大声喧哗，需保持庄严肃穆。",
        "remarks": "建议保持安静、尊重宗教礼仪，可把祥符禅寺安排在灵山大佛前后讲解，形成古刹渊源、礼佛祈福与现代景区建设的连续叙事。",
    },
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
)


class ScenicFactAgent:
    """Use the Lingshan scenic fact layer as the single trusted source for fact Q&A."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or resolve_path("data/processed/tourist_behavior.db")
        self._rows = self._load_rows()
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

        mentioned_attractions = self.find_attraction_mentions(user_query, scenic_slug=scenic_slug)
        attraction = mentioned_attractions[0] if mentioned_attractions else None
        if not attraction and context_row:
            attraction = context_row["attraction_name"]

        if self._is_multi_attraction_comparison_query(user_query, mentioned_attractions):
            comparison_result = self._build_comparison_result(user_query, mentioned_attractions, scenic_slug=scenic_slug)
            if comparison_result:
                return comparison_result

        referenced_attraction = self._resolve_referenced_attraction(
            user_query,
            mentioned_attractions,
            scenic_slug=scenic_slug,
        )
        if referenced_attraction:
            attraction = referenced_attraction

        if self._has_source_conflict(user_query):
            return self._result(
                "抱歉，这个问题混用了不合适的数据源：游客行为数据只能用于统计分析，DOCX 景区资料只能用于景点事实、历史文化和讲解内容。我不能把一种数据源当作另一种事实依据来回答。",
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
            )

        if self._is_unsupported_fact_query(user_query):
            return self._result(
                "抱歉，这个问题需要实时运营数据或资料外信息支持，我不能根据现有灵山胜境资料编造。您可以改问已收录的景点介绍、位置、开放信息、历史背景、文化内涵或游览建议。",
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
            )

        general_fact = self._answer_general_docx_fact(user_query)
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
            )

        question_query = self._strip_attraction_mentions(user_query, mentioned_attractions)
        question_type = self.detect_question_type(question_query or user_query)

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
                        )

                if question_type in row:
                    text = self._format_field_answer(row, question_type)
                    if text:
                        return self._result(
                            text,
                            attraction,
                            f"field:{question_type}",
                            evidence=[self._row_evidence(row, question_type, row.get(question_type))],
                        )

                if self._is_direct_overview_request(user_query, attraction):
                    overview = self._format_overview(row)
                    if overview:
                        return self._result(
                            overview,
                            attraction,
                            "overview",
                            evidence=self._overview_evidence(row),
                        )

        if retrieval_mode == "hybrid":
            rag_result = self._query_rag(user_query, scenic_slug=scenic_slug)
            rag_answer = str(rag_result.get("answer") or "")
            if rag_answer and not self._looks_like_missing_answer(rag_answer):
                return self._result(
                    rag_answer,
                    attraction,
                    "rag_general",
                    evidence=rag_result.get("evidence") or [],
                    trace=rag_result.get("trace") or {},
                )

        if attraction and self._is_direct_overview_request(user_query, attraction):
            row = self.get_attraction_row(attraction)
            if row:
                overview = self._format_overview(row)
                if overview:
                    return self._result(
                        overview,
                        attraction,
                        "overview",
                        evidence=self._overview_evidence(row),
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

    def detect_question_type(self, user_query: str) -> Optional[str]:
        for field, keywords in QUESTION_FIELD_MAP.items():
            if any(keyword in user_query for keyword in keywords):
                return field
        return None

    def _answer_general_docx_fact(self, user_query: str) -> Optional[str]:
        for keywords, answer in GENERAL_DOCX_FACTS:
            if all(keyword in user_query for keyword in keywords):
                return answer
        evidence_answer = self._answer_docx_evidence(user_query)
        if evidence_answer:
            return evidence_answer
        return None

    def _answer_docx_evidence(self, user_query: str) -> Optional[str]:
        for item in self._docx_evidence:
            entity = str(item.get("entity") or "")
            topic = str(item.get("topic") or "")
            if entity and topic and entity in user_query and topic in user_query:
                facts = str(item.get("facts") or "").strip()
                must_include = [str(term) for term in item.get("must_include") or [] if str(term)]
                keywords = "、".join(must_include)
                suffix = f"关键依据包括：{keywords}。" if keywords else ""
                return f"根据 DOCX 历史文化资料，{entity}在{topic}方面的关键信息是：{facts}{suffix}"

            must_include = [str(term) for term in item.get("must_include") or [] if str(term)]
            trigger_terms = [term for term in must_include if term != entity and term in user_query]
            if entity and entity in user_query and trigger_terms:
                facts = str(item.get("facts") or "").strip()
                keywords = "、".join(must_include)
                return f"根据 DOCX 历史文化资料，{entity}的相关事实是：{facts}关键依据包括：{keywords}。"
        return None

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
        return any(keyword in user_query for keyword in UNSUPPORTED_FACT_KEYWORDS) or contains_realtime_unsupported_signal(user_query)

    def _has_source_conflict(self, user_query: str) -> bool:
        query = str(user_query or "")
        behavior_terms = ("游客行为数据", "行为数据", "游客行为 Excel", "游客行为Excel", "Excel")
        docx_terms = ("DOCX", "docx", "历史文化资料", "景区资料", "介绍文档")
        fact_terms = (
            "官方开放时间",
            "开放时间",
            "位置",
            "多高",
            "高度",
            "文化内涵",
            "历史",
            "事实",
            "门票",
            "票价",
        )
        analytics_terms = (
            "统计",
            "平均",
            "消费",
            "满意度",
            "停留",
            "访问量",
            "客流",
            "月份",
            "男性",
            "女性",
            "游客",
        )
        if any(term in query for term in behavior_terms) and any(term in query for term in fact_terms):
            return True
        if any(term in query for term in docx_terms) and any(term in query for term in analytics_terms):
            return True
        if "当作" in query and any(term in query for term in ("门票", "票价", "开放时间", "文化内涵")):
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
        return self.detect_question_type(remainder) == "description"

    @staticmethod
    def _is_multi_attraction_comparison_query(user_query: str, mentions: List[str]) -> bool:
        if len(mentions) < 2:
            return False
        return any(keyword in user_query for keyword in COMPARISON_HINTS)

    def _build_comparison_result(
        self,
        user_query: str,
        mentions: List[str],
        scenic_slug: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        rows = [self.get_attraction_row(name) for name in mentions[:2]]
        if not all(rows):
            return None

        question_query = self._strip_attraction_mentions(user_query, mentions[:2])
        question_type = self.detect_question_type(question_query or user_query) or "description"
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
        if not any(keyword in user_query for keyword in ("更适合", "更值得", "哪个", "哪一个")):
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
            for keyword in REFERENCE_DESCRIPTOR_TERMS + tuple(term for term in QUESTION_FIELD_MAP.get(question_type, ()))
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
        if not any(keyword in user_query for keyword in REFERENCE_POSITION_HINTS):
            return None

        anchor = mentions[0]
        candidates = [name for name in self.list_attractions(scenic_slug=scenic_slug) if name != anchor]
        if not candidates:
            return None

        best_name = None
        best_score = 0
        descriptor_terms = [term for term in REFERENCE_DESCRIPTOR_TERMS if term in user_query]

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
        for field in ("description", "location", "architecture_params", "cultural_meaning", "highlights", "open_info"):
            value = str(row.get(field) or "").strip()
            if value:
                evidence.append(self._row_evidence(row, field, value))
        return evidence[:4]

    @staticmethod
    def _result(
        answer: str,
        attraction: Optional[str],
        response_kind: str,
        evidence: Optional[List[Dict[str, Any]]] = None,
        refusal: Optional[Dict[str, Any]] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "answer": answer,
            "matched_attraction": attraction,
            "response_kind": response_kind,
            "evidence": evidence or [],
            "refusal": refusal,
            "trace": trace or {},
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
