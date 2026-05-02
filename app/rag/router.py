from typing import Literal


QueryIntent = Literal["FACT", "ANALYTICS", "RECOMMEND"]


RECOMMEND_KEYWORDS = (
    "推荐",
    "路线",
    "行程",
    "怎么逛",
    "怎么玩",
    "怎么走",
    "怎么安排",
    "去哪里",
    "后面去哪里",
    "一日游",
    "半日游",
    "爱好者",
    "感兴趣",
    "关注",
    "重点看",
    "重点听",
    "互动感",
    "安排一下",
    "安排",
    "不想太累",
)

RECOMMEND_ROUTE_PHRASES = (
    "想体验",
    "下一步",
    "适合去",
    "去哪几个点",
    "哪些点",
    "规划",
    "设计一条",
    "主题路线",
    "不走回头路",
    "从入口开始",
)

RECOMMEND_INTEREST_HINTS = (
    "历史",
    "文化",
    "自然",
    "风光",
    "亲子",
    "建筑",
    "艺术",
    "慢游",
    "轻松",
    "拍照",
    "打卡",
)

ANALYTICS_KEYWORDS = (
    "游客",
    "人群",
    "偏好",
    "喜欢",
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
    "团体",
    "记录",
    "访问量",
    "月份",
    "景点类型",
    "最受欢迎",
)

STRONG_ANALYTICS_KEYWORDS = (
    "游客行为数据",
    "行为数据",
    "excel",
    "sql",
    "样本游客",
    "样本量",
    "统计",
    "分析",
    "平均",
    "人均",
    "消费",
    "花费",
    "停留",
    "满意度",
    "热门",
    "趋势",
    "年龄",
    "男性",
    "女性",
    "同行",
    "记录",
    "访问量",
    "月份",
    "景点类型",
    "top",
    "前5",
    "前五",
)

FACT_KEYWORDS = (
    "门票",
    "票价",
    "开放",
    "营业",
    "几点",
    "位置",
    "在哪",
    "哪里",
    "介绍",
    "历史",
    "文化",
    "背景",
    "亮点",
    "特色",
    "看点",
    "讲解",
    "为什么",
    "概述",
    "事实",
    "依据",
    "资料",
    "规模",
    "参数",
    "体验",
    "游览",
    "安排",
    "内涵",
    "寓意",
)

FACT_ROUTE_PHRASES = (
    "开放安排",
    "游览时需要注意",
    "向游客介绍",
    "给游客讲解",
    "规模参数",
    "核心功能",
    "文化内涵",
    "详细介绍",
    "游玩亮点",
    "历史文化资料",
    "docx 资料",
    "docx资料",
    "应该回答哪些事实",
    "不能讲错",
    "哪些依据",
)


def get_query_intent(query: str) -> QueryIntent:
    lowered = query.strip().lower()

    if any(term in lowered for term in ("游客行为数据", "行为数据", "游客行为 excel", "游客行为excel")) and any(
        term in lowered for term in ("官方开放时间", "开放时间", "位置", "多高", "高度", "文化内涵", "历史", "事实", "门票", "票价")
    ):
        return "FACT"

    if any(phrase in lowered for phrase in FACT_ROUTE_PHRASES):
        return "FACT"

    if "喜欢" in lowered and any(keyword in lowered for keyword in RECOMMEND_INTEREST_HINTS):
        return "RECOMMEND"

    if any(phrase in lowered for phrase in RECOMMEND_ROUTE_PHRASES) and any(
        keyword in lowered for keyword in RECOMMEND_INTEREST_HINTS
    ):
        return "RECOMMEND"

    if "路线" in lowered and any(keyword in lowered for keyword in ("会重点", "为什么适合", "适合看哪些")):
        return "FACT"

    if any(keyword in lowered for keyword in RECOMMEND_KEYWORDS):
        return "RECOMMEND"

    has_fact_signal = any(keyword in lowered for keyword in FACT_KEYWORDS)
    has_analytics_signal = any(keyword in lowered for keyword in ANALYTICS_KEYWORDS)
    has_strong_analytics_signal = any(keyword in lowered for keyword in STRONG_ANALYTICS_KEYWORDS)

    if has_strong_analytics_signal and not has_fact_signal:
        return "ANALYTICS"

    if has_strong_analytics_signal and has_analytics_signal:
        return "ANALYTICS"

    return "FACT"
