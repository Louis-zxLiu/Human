from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from app.core.scenic_catalog import infer_scenic_slug_from_text


QueryIntent = Literal["FACT", "ANALYTICS", "RECOMMEND"]
ExecutionStrategy = Literal[
    "structured_fact",
    "hybrid_rag",
    "semantic_sql",
    "route_planner",
    "refuse_realtime",
    "refuse_source_conflict",
]


RECOMMEND_KEYWORDS = (
    "推荐",
    "路线",
    "行程",
    "怎么逛",
    "怎么玩",
    "怎么走",
    "怎么安排",
    "应该怎么逛",
    "适合怎么逛",
    "怎么游览",
    "如何游览",
    "帮我安排",
    "帮我规划",
    "路线怎么走",
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


class QueryPlanner:
    """Decide the cheapest reliable execution path before invoking any agent."""

    def plan(self, user_query: str, scenic_slug: Optional[str] = None) -> QueryPlan:
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
            )

        if self._requires_realtime_data(lowered):
            return QueryPlan(
                intent=self._default_intent(lowered),
                strategy="refuse_realtime",
                scenic_slug=resolved_scenic_slug,
                requires_realtime_data=True,
                confidence=0.96,
                reasoning=["Query asks for realtime or future operational data."],
            )

        if self._is_recommend_query(lowered):
            return QueryPlan(
                intent="RECOMMEND",
                strategy="route_planner",
                scenic_slug=resolved_scenic_slug,
                route_profile=self._detect_route_profile(lowered),
                confidence=0.9,
                reasoning=["Detected route-planning or recommendation language."],
            )

        if self._is_analytics_query(lowered):
            return QueryPlan(
                intent="ANALYTICS",
                strategy="semantic_sql",
                scenic_slug=resolved_scenic_slug,
                confidence=0.9,
                reasoning=["Detected behavior-analysis language or metrics."],
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
            )

        return QueryPlan(
            intent="FACT",
            strategy="structured_fact",
            scenic_slug=resolved_scenic_slug,
            question_type=question_type,
            confidence=0.84,
            reasoning=["Defaulted to structured scenic facts for precise fact answering."],
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
    def _is_analytics_query(query: str) -> bool:
        if any(phrase in query for phrase in FACT_GUIDE_PHRASES):
            return False
        has_strong_signal = any(keyword in query for keyword in ANALYTICS_STRONG_KEYWORDS)
        if not has_strong_signal:
            return False
        return any(keyword in query for keyword in ANALYTICS_KEYWORDS) or has_strong_signal

    @staticmethod
    def _requires_realtime_data(query: str) -> bool:
        return contains_realtime_unsupported_signal(query)

    @staticmethod
    def _prefers_hybrid_rag(query: str, question_type: str) -> bool:
        if any(keyword in query for keyword in RAG_INTENSIVE_HINTS):
            return True
        return question_type in {"history", "description", "cultural_meaning"} and any(
            keyword in query for keyword in ("概况", "整体", "为什么", "资料", "依据", "背景", "内涵")
        )

    @staticmethod
    def _detect_route_profile(query: str) -> str:
        for profile, keywords in RECOMMEND_PROFILE_HINTS.items():
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
