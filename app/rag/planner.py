from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from app.core.config import settings
from app.core.scenic_catalog import infer_scenic_slug_from_text
from app.rag.llm_client import generate_chat_completion, llm_is_configured
from app.rag.rule_config import load_json_config, term_map, term_tuple
from app.rag.router_cache import RouterPlanCache


QueryIntent = Literal["FACT", "ANALYTICS", "RECOMMEND", "CHAT"]
ExecutionStrategy = Literal[
    "structured_fact",
    "hybrid_rag",
    "semantic_sql",
    "route_planner",
    "refuse_realtime",
    "refuse_source_conflict",
    "general_chat",
]


RECOMMEND_KEYWORDS = (
    "推荐",
    "路线",
    "行程",
    "怎么逛",
    "咋逛",
    "怎么玩",
    "怎么走",
    "咋走",
    "怎么安排",
    "应该怎么逛",
    "适合怎么逛",
    "怎么游览",
    "如何游览",
    "帮我安排",
    "帮我规划",
    "路线怎么走",
    "每站",
    "先去哪",
    "适合去哪些点",
    "去哪",
    "后面去哪里",
    "一日游",
    "半日游",
    "主题路线",
    "规划",
)

RECOMMEND_PROFILE_HINTS = {
    "history": ("历史", "文化", "人文", "佛教", "禅意"),
    "nature": ("自然", "风光", "湖景", "拍照", "打卡", "花海"),
    "family": ("亲子", "孩子", "家庭", "老人"),
    "architecture": ("建筑", "艺术", "空间", "坛城", "梵宫", "工艺"),
    "relaxed": ("轻松", "慢游", "不累", "休闲", "夜游"),
}

ANALYTICS_KEYWORDS = (
    "人群",
    "偏好",
    "消费",
    "花费",
    "停留",
    "满意度",
    "热门",
    "趋势",
    "年龄",
    "男性",
    "女性",
    "统计",
    "分析",
    "数据",
    "人均",
    "同行",
    "记录",
    "访问量",
    "月份",
    "景点类型",
    "sql",
    "excel",
)

ANALYTICS_STRONG_KEYWORDS = (
    "游客行为数据",
    "行为数据",
    "统计",
    "分析",
    "数据",
    "人均",
    "平均",
    "消费",
    "花费",
    "满意度",
    "停留",
    "访问量",
    "月份",
    "景点类型",
    "sql",
    "excel",
)

FACT_GUIDE_PHRASES = (
    "向游客介绍",
    "给游客讲解",
    "如果向游客介绍",
    "适合重点体验什么",
    "详细介绍里有什么重点",
    "应该讲哪些事实",
    "讲哪些事实",
)

FACT_FIELD_KEYWORDS = {
    "open_info": ("开放", "开放时间", "营业", "几点", "什么时候", "开门", "闭园", "演出时间", "门票", "票价"),
    "location": ("位置", "在哪", "哪里", "怎么走", "方位", "导航"),
    "architecture_params": ("建筑", "景观参数", "规模", "多高", "多大", "造型", "参数"),
    "highlights": ("亮点", "特色", "看点", "值得看", "必看", "推荐理由", "体验", "游玩"),
    "remarks": ("建议", "注意", "提醒", "打卡", "拍照"),
    "history": ("历史", "来历", "渊源", "背景", "故事", "典故", "为什么"),
    "cultural_meaning": ("文化", "寓意", "含义", "象征", "精神"),
    "core_function": ("作用", "用途", "功能"),
    "description": ("介绍", "讲解", "概况", "概述", "是什么"),
}

RAG_INTENSIVE_HINTS = (
    "根据历史文化资料",
    "根据景区资料",
    "历史文化资料",
    "景区概况",
    "整体概况",
    "为什么叫",
    "核心文化内涵",
    "世界佛教论坛",
    "佛教艺术",
    "传统工艺",
    "现代科技",
    "资料里",
    "关键依据",
)

REALTIME_UNSUPPORTED_HINTS = (
    "实时",
    "现在排队",
    "排队要多久",
    "当前停车",
    "剩多少车位",
    "今天客流",
    "现在客流",
    "明天",
    "预测",
    "最新票价",
    "最新开放时间",
)

REALTIME_TIME_HINTS = (
    "今天",
    "今天下午",
    "今天晚上",
    "现在",
    "当前",
    "实时",
    "这会儿",
    "刚刚",
    "稍后",
    "等会",
    "今晚",
    "明天",
)

REALTIME_WEATHER_HINTS = (
    "天气",
    "下雨",
    "雨",
    "晴",
    "阴",
    "多云",
    "气温",
    "温度",
    "风力",
    "风大",
    "空气质量",
)

REALTIME_TRAFFIC_HINTS = (
    "堵不堵",
    "堵车",
    "路况",
    "拥堵",
    "交通",
    "停车",
    "车位",
    "排队",
    "客流",
)

DOCX_TERMS = ("docx", "DOCX", "历史文化资料", "景区资料", "介绍文档")
BEHAVIOR_TERMS = ("游客行为数据", "行为数据", "游客行为 excel", "游客行为excel", "excel", "sql")
FACT_TERMS = (
    "开放时间",
    "位置",
    "多高",
    "高度",
    "文化内涵",
    "历史",
    "事实",
    "门票",
    "票价",
    "介绍",
)

PLANNER_RULE_CONFIG = load_json_config("app/rag/config/planner_rules.json")


@dataclass
class QueryPlan:
    intent: QueryIntent
    strategy: ExecutionStrategy
    scenic_slug: Optional[str] = None
    question_type: str = "description"
    route_profile: str = "general"
    requires_realtime_data: bool = False
    source_conflict: bool = False
    confidence: float = 0.8
    reasoning: List[str] = field(default_factory=list)
    chat_reply: str = ""
    planner_source: str = "heuristic"
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class QueryPlanner:
    """Decide the cheapest reliable execution path before invoking any agent."""

    def __init__(self, cache: Optional[RouterPlanCache] = None) -> None:
        self.cache = cache or RouterPlanCache()

    def plan(self, user_query: str, scenic_slug: Optional[str] = None) -> QueryPlan:
        llm_plan = self._plan_with_llm(user_query, scenic_slug=scenic_slug)
        if llm_plan:
            return llm_plan
        return self._heuristic_plan(user_query, scenic_slug=scenic_slug)

    def _heuristic_plan(self, user_query: str, scenic_slug: Optional[str] = None) -> QueryPlan:
        query = str(user_query or "").strip()
        lowered = query.lower()
        resolved_scenic_slug = scenic_slug or infer_scenic_slug_from_text(query)

        if self._has_source_conflict(lowered):
            return QueryPlan(
                intent="FACT",
                strategy="refuse_source_conflict",
                scenic_slug=resolved_scenic_slug,
                source_conflict=True,
                confidence=0.98,
                reasoning=["Detected mixed fact/analytics source requirements."],
                planner_source="heuristic_fallback",
            )

        if self._is_private_or_live_location_query(query):
            return QueryPlan(
                intent="ANALYTICS",
                strategy="refuse_realtime",
                scenic_slug=resolved_scenic_slug,
                requires_realtime_data=True,
                confidence=0.98,
                reasoning=["Query asks for a specific user's live/private location."],
                planner_source="heuristic_fallback",
            )

        if self._requires_realtime_data(lowered):
            return QueryPlan(
                intent=self._default_intent(lowered),
                strategy="refuse_realtime",
                scenic_slug=resolved_scenic_slug,
                requires_realtime_data=True,
                confidence=0.96,
                reasoning=["Query asks for realtime or future operational data."],
                planner_source="heuristic_fallback",
            )

        if self._is_route_planning_request(query):
            return QueryPlan(
                intent="RECOMMEND",
                strategy="route_planner",
                scenic_slug=resolved_scenic_slug,
                route_profile=self._detect_route_profile(lowered),
                confidence=0.92,
                reasoning=["Detected an actual route-planning request."],
                planner_source="heuristic_fallback",
            )

        if self._is_fact_data_question(query):
            question_type = self.detect_fact_question_type(query)
            return QueryPlan(
                intent="FACT",
                strategy="structured_fact",
                scenic_slug=resolved_scenic_slug,
                question_type=question_type,
                confidence=0.92,
                reasoning=["Named scenic fact asks for factual data, not behavior analytics."],
                planner_source="heuristic_fallback",
            )

        if self._is_recommend_query(lowered):
            return QueryPlan(
                intent="RECOMMEND",
                strategy="route_planner",
                scenic_slug=resolved_scenic_slug,
                route_profile=self._detect_route_profile(lowered),
                confidence=0.9,
                reasoning=["Detected route-planning or recommendation language."],
                planner_source="heuristic_fallback",
            )

        if self._is_analytics_query(lowered):
            return QueryPlan(
                intent="ANALYTICS",
                strategy="semantic_sql",
                scenic_slug=resolved_scenic_slug,
                confidence=0.9,
                reasoning=["Detected behavior-analysis language or metrics."],
                planner_source="heuristic_fallback",
            )

        question_type = self.detect_fact_question_type(query)
        if self._prefers_hybrid_rag(lowered, question_type):
            return QueryPlan(
                intent="FACT",
                strategy="hybrid_rag",
                scenic_slug=resolved_scenic_slug,
                question_type=question_type,
                confidence=0.82,
                reasoning=["Broad or document-style fact question; prefer hybrid retrieval."],
                planner_source="heuristic_fallback",
            )

        return QueryPlan(
            intent="FACT",
            strategy="structured_fact",
            scenic_slug=resolved_scenic_slug,
            question_type=question_type,
            confidence=0.84,
            reasoning=["Defaulted to structured scenic facts for precise fact answering."],
            planner_source="heuristic_fallback",
        )

    def _plan_with_llm(self, user_query: str, scenic_slug: Optional[str] = None) -> Optional[QueryPlan]:
        query = str(user_query or "").strip()
        if not query:
            return None

        resolved_scenic_slug = scenic_slug or infer_scenic_slug_from_text(query)
        cached = self.cache.get(query, resolved_scenic_slug, settings.LLM_MODEL_NAME)
        cached_payload = cached.get("payload") if cached else None
        if isinstance(cached_payload, dict):
            plan = self._plan_from_payload(
                cached_payload,
                resolved_scenic_slug=resolved_scenic_slug,
                user_query=query,
                planner_source="llm_cache",
            )
            if plan:
                return plan

        if not llm_is_configured():
            return None

        system_prompt = (
            "你是景区问答系统的路由器。你只做意图和执行路径判断，不回答问题。"
            "必须输出严格 JSON，不要输出 Markdown。"
        )
        prompt = (
            "请为用户问题选择唯一执行路径。\n"
            "意图定义：\n"
            "- FACT：景区事实、位置、开放信息、文化历史、讲解内容、景点介绍。\n"
            "- ANALYTICS：基于游客行为样本/Excel/SQL 的统计分析，包括记录数、平均、人均、最多、最高、分布、排名、年龄、性别、消费、满意度、停留时长、景点类型。\n"
            "- RECOMMEND：路线规划、怎么逛、下一步去哪、带老人/孩子、偏好主题、从入口开始、GPS 不准时的游览建议。\n"
            "- CHAT：简短寒暄、感谢、告别、确认、询问助手身份，且不包含景区任务。\n\n"
            "策略定义：\n"
            "- structured_fact：可从景点结构化事实表回答的 FACT。\n"
            "- hybrid_rag：需要 DOCX/历史文化资料、景区整体概况、宽泛讲解依据的 FACT。\n"
            "- semantic_sql：游客行为统计分析。\n"
            "- route_planner：路线/推荐/游览安排。\n"
            "- refuse_realtime：实时、当前、今天/明天/下周、天气、排队、停车、交通、预测、隐私或外部系统才知道的问题。\n"
            "- refuse_source_conflict：要求用错误数据源回答，例如用游客行为数据证明官方事实、用 DOCX 统计行为数据、把平均消费当官方票价。\n"
            "- general_chat：普通寒暄。\n\n"
            "重要规则：\n"
            "1. 不要依赖固定关键词，按语义判断。即使没有“游客行为数据”字样，只要在问样本统计/平均/排名/分布，也应为 ANALYTICS + semantic_sql。\n"
            "2. 口语问法也要识别，例如“有啥用”是 core_function，“有啥好玩的”是 highlights，“尺寸材质”是 architecture_params。\n"
            "3. 问“灵山胜境概况/规模/文化称号”这类景区级事实时，用 FACT + hybrid_rag，不要要求补充具体景点。\n"
            "4. 边界/拒答策略优先级最高。凡是询问未来预测、实时状态、当前排队/车位/客流/天气/交通、隐私推断、外部景区实时信息，必须 strategy=refuse_realtime，不能用历史均值代替预测。\n"
            "5. 凡是要求用错误数据源回答，必须 strategy=refuse_source_conflict。例如用游客行为数据证明官方开放时间/高度，或用 DOCX 统计游客平均消费。\n\n"
            "参考例子：\n"
            "- “总共有多少条记录？” => ANALYTICS + semantic_sql\n"
            "- “哪5个景点去的人最多？” => ANALYTICS + semantic_sql\n"
            "- “灵山大照壁有啥用？” => FACT + structured_fact + core_function\n"
            "- “灵山胜境概况里重点讲啥？” => FACT + hybrid_rag + description\n"
            "- “喜欢佛教文化，灵山胜境咋逛？” => RECOMMEND + route_planner + history\n"
            "- “下周游客满意度大概多少？” => ANALYTICS + refuse_realtime，requires_realtime_data=true\n"
            "- “灵山胜境今天实时有多少人？” => FACT + refuse_realtime，requires_realtime_data=true\n"
            "- “灵山大佛几点开门？从行为数据查。” => FACT + refuse_source_conflict，source_conflict=true\n\n"
            "字段要求：\n"
            "{\n"
            '  "intent": "FACT|ANALYTICS|RECOMMEND|CHAT",\n'
            '  "strategy": "structured_fact|hybrid_rag|semantic_sql|route_planner|refuse_realtime|refuse_source_conflict|general_chat",\n'
            '  "question_type": "location|open_info|architecture_params|highlights|remarks|history|cultural_meaning|core_function|description",\n'
            '  "route_profile": "history|nature|family|architecture|relaxed|general",\n'
            '  "requires_realtime_data": true/false,\n'
            '  "source_conflict": true/false,\n'
            '  "confidence": 0.0-1.0,\n'
            '  "chat_reply": "仅当 general_chat 时给一句24字以内中文回复，否则为空",\n'
            '  "reasoning": ["一句话说明"]\n'
            "}\n\n"
            f"已知 scenic_slug：{resolved_scenic_slug or 'unknown'}\n"
            f"用户问题：{query}\n"
            "只输出 JSON。"
        )

        raw = generate_chat_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.0,
            max_tokens=500,
            return_error_text=False,
        )
        payload = self._parse_json(raw)
        if not payload:
            return None
        self.cache.set(query, resolved_scenic_slug, settings.LLM_MODEL_NAME, payload)
        return self._plan_from_payload(payload, resolved_scenic_slug=resolved_scenic_slug, user_query=query)

    def cache_stats(self) -> Dict[str, Any]:
        return self.cache.stats()

    def clear_cache(self, drop_file: bool = True) -> None:
        self.cache.clear(drop_file=drop_file)

    @staticmethod
    def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
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

    @staticmethod
    def _plan_from_payload(
        payload: Dict[str, Any],
        resolved_scenic_slug: Optional[str],
        user_query: str = "",
        planner_source: str = "llm",
    ) -> Optional[QueryPlan]:
        allowed_intents = {"FACT", "ANALYTICS", "RECOMMEND", "CHAT"}
        allowed_strategies = {
            "structured_fact",
            "hybrid_rag",
            "semantic_sql",
            "route_planner",
            "refuse_realtime",
            "refuse_source_conflict",
            "general_chat",
        }
        allowed_question_types = {
            "location",
            "open_info",
            "architecture_params",
            "highlights",
            "remarks",
            "history",
            "cultural_meaning",
            "core_function",
            "description",
        }
        allowed_profiles = {"history", "nature", "family", "architecture", "relaxed", "general"}

        intent = str(payload.get("intent") or "").strip().upper()
        strategy = str(payload.get("strategy") or "").strip()
        if intent not in allowed_intents or strategy not in allowed_strategies:
            return None

        requires_realtime_data = QueryPlanner._coerce_bool(payload.get("requires_realtime_data"))
        source_conflict = QueryPlanner._coerce_bool(payload.get("source_conflict"))
        query = str(user_query or "")
        if source_conflict:
            strategy = "refuse_source_conflict"
        elif strategy == "refuse_realtime" and QueryPlanner._is_historical_analytics_query(query):
            strategy = "semantic_sql"
            requires_realtime_data = False
        elif requires_realtime_data and not QueryPlanner._is_historical_analytics_query(query):
            strategy = "refuse_realtime"
        elif requires_realtime_data:
            requires_realtime_data = False

        strategy_intent = {
            "semantic_sql": "ANALYTICS",
            "route_planner": "RECOMMEND",
            "general_chat": "CHAT",
        }
        if strategy in strategy_intent:
            intent = strategy_intent[strategy]

        if QueryPlanner._is_private_or_live_location_query(query):
            strategy = "refuse_realtime"
            intent = "ANALYTICS"
            requires_realtime_data = True
        if strategy == "general_chat" and QueryPlanner._has_boundary_or_domain_task(query):
            return None
        if strategy == "semantic_sql" and QueryPlanner._is_fact_data_question(query):
            strategy = "structured_fact"
            intent = "FACT"
        if strategy in {"structured_fact", "hybrid_rag"} and QueryPlanner._is_analytics_query(query):
            strategy = "semantic_sql"
            intent = "ANALYTICS"
        route_planning_request = QueryPlanner._is_route_planning_request(query)
        if strategy in {"structured_fact", "hybrid_rag"} and route_planning_request:
            strategy = "route_planner"
            intent = "RECOMMEND"
        if strategy == "route_planner" and (
            QueryPlanner._is_fact_experience_question(query)
            or (QueryPlanner._is_fact_data_question(query) and not route_planning_request)
        ):
            strategy = "structured_fact"
            intent = "FACT"
        if strategy == "refuse_realtime" and QueryPlanner._is_historical_analytics_query(query):
            strategy = "semantic_sql"
            intent = "ANALYTICS"
            requires_realtime_data = False
        if strategy in {"refuse_realtime", "refuse_source_conflict"} and intent == "CHAT":
            intent = QueryPlanner._default_intent(query)

        question_type = str(payload.get("question_type") or "description").strip()
        if question_type not in allowed_question_types:
            question_type = "description"

        route_profile = str(payload.get("route_profile") or "general").strip()
        if route_profile not in allowed_profiles:
            route_profile = "general"

        try:
            confidence = float(payload.get("confidence", 0.8))
        except (TypeError, ValueError):
            confidence = 0.8
        confidence = max(0.0, min(confidence, 1.0))

        reasoning_payload = payload.get("reasoning") or []
        if isinstance(reasoning_payload, str):
            reasoning = [reasoning_payload]
        elif isinstance(reasoning_payload, list):
            reasoning = [str(item) for item in reasoning_payload[:4]]
        else:
            reasoning = []

        return QueryPlan(
            intent=intent,  # type: ignore[arg-type]
            strategy=strategy,  # type: ignore[arg-type]
            scenic_slug=resolved_scenic_slug,
            question_type=question_type,
            route_profile=route_profile,
            requires_realtime_data=requires_realtime_data,
            source_conflict=source_conflict,
            confidence=confidence,
            reasoning=reasoning or ["LLM planner selected route."],
            chat_reply=str(payload.get("chat_reply") or "").strip(),
            planner_source=planner_source,
            raw_payload=payload,
        )

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                return True
            if lowered in {"false", "0", "no", "n", ""}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        return False

    @staticmethod
    def _is_historical_analytics_query(query: str) -> bool:
        if not query:
            return False
        has_past_sample_time = bool(re.search(r"2025\s*年|2025[-/]\d{1,2}", query))
        has_metric = any(
            term in query
            for term in (
                "平均",
                "人均",
                "总共",
                "一共",
                "多少",
                "满意度",
                "停留",
                "逛多久",
                "消费",
                "花",
                "同行",
                "访问",
                "游客",
                "一般",
                "几个人",
                "一起来",
                "一起玩",
                "哪类",
                "哪种",
                "类型",
                "最受欢迎",
                "最火",
                "去的人最多",
            )
        )
        has_live_signal = any(term in query for term in ("实时", "现在", "当前", "今天", "明天", "下周", "预测", "排队", "车位", "天气"))
        return has_past_sample_time and has_metric and not has_live_signal

    @staticmethod
    def _has_boundary_or_domain_task(query: str) -> bool:
        return any(
            term in query
            for term in (
                "编",
                "推断",
                "手机号",
                "真实姓名",
                "夜场",
                "实时",
                "游客",
                "景区",
                "景点",
                "灵山",
                "拈花湾",
                "路线",
                "数据",
                "统计",
            )
        )

    @staticmethod
    def detect_fact_question_type(user_query: str) -> str:
        for field, keywords in FACT_FIELD_KEYWORDS.items():
            if any(keyword in user_query for keyword in keywords):
                return field
        return "description"

    @staticmethod
    def _is_recommend_query(query: str) -> bool:
        return any(keyword in query for keyword in RECOMMEND_KEYWORDS)

    @staticmethod
    def _is_route_planning_request(query: str) -> bool:
        if not QueryPlanner._is_recommend_query(query):
            return False
        fact_function_terms = term_tuple(
            PLANNER_RULE_CONFIG,
            "route_planning",
            "fact_function_terms",
            fallback=("作用", "功能", "用途", "干什么", "干啥", "起啥"),
        )
        if any(term in query for term in fact_function_terms) and not any(
            term in query
            for term in term_tuple(
                PLANNER_RULE_CONFIG,
                "route_planning",
                "override_allow_terms",
                fallback=("推荐", "规划", "安排", "怎么走", "咋走", "怎么逛", "咋逛", "每站", "下一步"),
            )
        ):
            return False
        route_request_terms = term_tuple(
            PLANNER_RULE_CONFIG,
            "route_planning",
            "request_terms",
            fallback=(
                "推荐",
                "路线怎么",
                "路线咋",
                "路线如何",
                "路线",
                "行程",
                "怎么安排",
                "怎么规划",
                "怎么走",
                "咋走",
                "怎么逛",
                "咋逛",
                "怎么游览",
                "如何游览",
                "每站",
                "下一步",
                "不走回头路",
                "带时长",
                "安排",
                "规划",
                "核心景点",
            ),
        )
        return any(term in query for term in route_request_terms)

    @staticmethod
    def _is_fact_experience_question(query: str) -> bool:
        return any(
            term in query
            for term in term_tuple(
                PLANNER_RULE_CONFIG,
                "route_planning",
                "experience_terms",
                fallback=("特别推荐的体验", "推荐的体验", "有什么特别", "哪里最值得去", "亮点有哪些"),
            )
        ) and not any(
            term in query
            for term in term_tuple(
                PLANNER_RULE_CONFIG,
                "route_planning",
                "experience_exclude_terms",
                fallback=("路线", "怎么走", "怎么逛", "下一站", "下一步", "安排", "规划"),
            )
        )

    @staticmethod
    def _is_analytics_query(query: str) -> bool:
        if any(phrase in query for phrase in FACT_GUIDE_PHRASES):
            return False
        if QueryPlanner._is_fact_data_question(query):
            return False
        if re.search(r"2025\s*年\s*\d{1,2}\s*月", query) and QueryPlanner._is_historical_analytics_query(query):
            return True
        if any(
            term in query
            for term in term_tuple(
                PLANNER_RULE_CONFIG,
                "analytics",
                "direct_terms",
                fallback=(
                    "最小孩子几岁",
                    "最小几岁",
                    "几岁",
                    "哪类景点",
                    "哪种景点",
                    "景点类型",
                    "有多少人",
                    "多少游客",
                    "逛多久",
                    "一般逛多久",
                    "待多久",
                    "停留多久",
                ),
            )
        ):
            return True
        has_strong_signal = any(keyword in query for keyword in ANALYTICS_STRONG_KEYWORDS)
        if not has_strong_signal:
            return False
        return any(keyword in query for keyword in ANALYTICS_KEYWORDS) or has_strong_signal

    @staticmethod
    def _requires_realtime_data(query: str) -> bool:
        return contains_realtime_unsupported_signal(query)

    @staticmethod
    def _is_private_or_live_location_query(query: str) -> bool:
        return bool(re.search(r"(?<![A-Za-z0-9])U\d{3,}", query, flags=re.IGNORECASE)) and any(
            term in query for term in ("位置", "在哪", "哪里", "定位", "轨迹")
        )

    @staticmethod
    def _is_fact_data_question(query: str) -> bool:
        fact_entities = term_tuple(
            PLANNER_RULE_CONFIG,
            "fact_detection",
            "entities",
            fallback=(
                "灵山",
                "灵山胜境",
                "五印坛城",
                "灵山梵宫",
                "九龙灌浴",
                "祥符禅寺",
                "灵山大佛",
                "菩提大道",
                "降魔浮雕",
                "百子戏弥勒",
                "五智门",
            ),
        )
        fact_asks = term_tuple(
            PLANNER_RULE_CONFIG,
            "fact_detection",
            "asks",
            fallback=("介绍", "要说", "哪些数据", "什么数据", "资料", "依据", "关键", "核心", "位置", "规模", "建筑", "作用", "功能", "用途"),
        )
        behavior_signals = term_tuple(
            PLANNER_RULE_CONFIG,
            "fact_detection",
            "behavior_signals",
            fallback=("游客行为", "行为数据", "平均", "人均", "消费", "满意度", "访问量", "接待", "多少游客"),
        )
        return any(entity in query for entity in fact_entities) and any(term in query for term in fact_asks) and not any(
            signal in query for signal in behavior_signals
        )

    @staticmethod
    def _prefers_hybrid_rag(query: str, question_type: str) -> bool:
        if any(
            keyword in query
            for keyword in term_tuple(
                PLANNER_RULE_CONFIG,
                "hybrid_rag",
                "intensive_hints",
                fallback=RAG_INTENSIVE_HINTS,
            )
        ):
            return True
        return question_type in {"history", "description", "cultural_meaning"} and any(
            keyword in query
            for keyword in term_tuple(
                PLANNER_RULE_CONFIG,
                "hybrid_rag",
                "question_type_terms",
                fallback=("概况", "整体", "为什么", "资料", "依据", "背景", "内涵"),
            )
        )

    @staticmethod
    def _detect_route_profile(query: str) -> str:
        if any(
            term in query
            for term in term_tuple(
                PLANNER_RULE_CONFIG,
                "route_profiles",
                "relaxed",
                fallback=("不累", "轻松", "慢游", "老人", "长辈"),
            )
        ):
            return "relaxed"
        for profile, keywords in term_map(
            PLANNER_RULE_CONFIG,
            "route_profiles",
            fallback=RECOMMEND_PROFILE_HINTS,
        ).items():
            if any(keyword in query for keyword in keywords):
                return profile
        return "general"

    @staticmethod
    def _has_source_conflict(query: str) -> bool:
        has_docx = any(term.lower() in query for term in DOCX_TERMS)
        has_behavior = any(term.lower() in query for term in BEHAVIOR_TERMS)
        has_fact = any(term in query for term in FACT_TERMS)
        has_analytics = any(term in query for term in ANALYTICS_KEYWORDS)
        analytics_metric_terms = (
            "统计",
            "平均",
            "消费",
            "花费",
            "满意度",
            "访问量",
            "偏好",
            "停留",
            "记录",
            "排名",
            "分布",
            "人群",
            "性别",
            "年龄",
            "同行",
            "月份",
            "景点类型",
        )
        has_behavior_metric = any(term in query for term in analytics_metric_terms)
        if has_docx and has_analytics:
            return True
        if "官方" in query and has_behavior and has_fact:
            return True
        if has_behavior and has_fact and not has_behavior_metric:
            return True
        if "当作" in query and any(term in query for term in ("门票", "票价", "开放时间", "文化内涵")):
            return True
        return False

    @staticmethod
    def _default_intent(query: str) -> QueryIntent:
        if any(keyword in query for keyword in ANALYTICS_KEYWORDS):
            return "ANALYTICS"
        if any(keyword in query for keyword in RECOMMEND_KEYWORDS):
            return "RECOMMEND"
        return "FACT"


def contains_realtime_unsupported_signal(query: str) -> bool:
    if any(keyword in query for keyword in REALTIME_UNSUPPORTED_HINTS):
        return True

    has_time_anchor = any(keyword in query for keyword in REALTIME_TIME_HINTS)
    weather_related = any(keyword in query for keyword in REALTIME_WEATHER_HINTS)
    traffic_related = any(keyword in query for keyword in REALTIME_TRAFFIC_HINTS)

    if has_time_anchor and (weather_related or traffic_related):
        return True

    if weather_related and any(keyword in query for keyword in ("会不会", "是否", "能不能", "怎么样")):
        return True

    return False
