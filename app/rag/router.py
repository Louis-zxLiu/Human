from typing import Literal


QueryIntent = Literal["FACT", "ANALYTICS", "RECOMMEND"]


RECOMMEND_KEYWORDS = (
    "推荐",
    "路线",
    "行程",
    "适合",
    "怎么玩",
    "怎么逛",
    "先去",
    "一日游",
    "半日游",
    "爱好者",
    "感兴趣",
)

RECOMMEND_INTEREST_HINTS = ("历史", "文化", "自然", "风光", "亲子", "建筑", "艺术", "慢游", "轻松")

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
    "最多",
    "最受欢迎",
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
    "路线图",
)


def get_query_intent(query: str) -> QueryIntent:
    lowered = query.strip().lower()

    if any(keyword in lowered for keyword in RECOMMEND_KEYWORDS):
        return "RECOMMEND"
    if "喜欢" in lowered and any(keyword in lowered for keyword in RECOMMEND_INTEREST_HINTS):
        return "RECOMMEND"

    has_fact_signal = any(keyword in lowered for keyword in FACT_KEYWORDS)
    has_analytics_signal = any(keyword in lowered for keyword in ANALYTICS_KEYWORDS)

    if has_analytics_signal and not has_fact_signal:
        return "ANALYTICS"

    if has_analytics_signal and any(
        keyword in lowered for keyword in ("满意度", "消费", "停留", "人均", "偏好", "趋势", "女性", "男性", "年龄", "游客")
    ):
        return "ANALYTICS"

    return "FACT"
