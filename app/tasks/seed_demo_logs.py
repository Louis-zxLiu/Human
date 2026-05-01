import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.core.config import resolve_path
from app.services.log_service import log_service


DEMO_INTERACTIONS: List[Dict[str, Any]] = [
    {
        "user_query": "我第一次来，帮我推荐 90 分钟游览路线",
        "ai_response": "推荐路线：灵山大照壁 -> 九龙灌浴 -> 祥符禅寺 -> 灵山大佛。适合第一次到访游客快速覆盖核心节点。",
        "intent_type": "路线推荐",
        "sentiment": "正面",
        "focus_point": "经典首游",
        "query_scope": "RECOMMEND",
        "matched_attraction": "灵山大佛",
        "recommendation_label": "经典首游",
        "response_kind": "recommendation",
        "cost_time": 3.2,
    },
    {
        "user_query": "我是历史文化爱好者，请给我一条深度讲解路线",
        "ai_response": "建议重点讲解祥符禅寺、灵山大佛和灵山梵宫，串联唐代渊源、五方五佛和佛教艺术。",
        "intent_type": "路线推荐",
        "sentiment": "正面",
        "focus_point": "历史文化",
        "query_scope": "RECOMMEND",
        "matched_attraction": "祥符禅寺",
        "recommendation_label": "历史文化",
        "response_kind": "recommendation",
        "cost_time": 3.6,
    },
    {
        "user_query": "带孩子来玩，有哪些适合亲子的互动点？",
        "ai_response": "亲子路线可选择百子戏弥勒、九龙灌浴、佛教文化博览馆和灵山大佛，便于用故事和互动理解景区文化。",
        "intent_type": "路线推荐",
        "sentiment": "正面",
        "focus_point": "亲子同游",
        "query_scope": "RECOMMEND",
        "matched_attraction": "九龙灌浴",
        "recommendation_label": "亲子同游",
        "response_kind": "recommendation",
        "cost_time": 3.9,
    },
    {
        "user_query": "灵山梵宫为什么被称为佛教艺术的卢浮宫？",
        "ai_response": "灵山梵宫融合佛教艺术、传统工艺和现代声光技术，因此被称为佛教艺术的东方卢浮宫。",
        "intent_type": "景点问答",
        "sentiment": "中性",
        "focus_point": "灵山梵宫",
        "query_scope": "FACT",
        "matched_attraction": "灵山梵宫",
        "recommendation_label": "",
        "response_kind": "docx_general",
        "cost_time": 2.1,
    },
    {
        "user_query": "平均停留时间最长的景点是哪几个？",
        "ai_response": "基于游客行为数据分析，平均停留时间最长的景点包括锦江乐园、杭州Hello Kitty乐园、上海欢乐谷。",
        "intent_type": "数据分析",
        "sentiment": "中性",
        "focus_point": "停留时长",
        "query_scope": "ANALYTICS",
        "matched_attraction": "",
        "recommendation_label": "",
        "response_kind": "analytics",
        "cost_time": 1.4,
    },
    {
        "user_query": "我现在定位不准，只看到一座桥和很长的步道，下一站怎么走？",
        "ai_response": "弱 GPS 场景下，我会先请您补充地标；根据桥和步道描述，可能靠近五明桥或菩提大道。",
        "intent_type": "问路导航",
        "sentiment": "中性",
        "focus_point": "弱GPS",
        "query_scope": "RECOMMEND",
        "matched_attraction": "五明桥",
        "recommendation_label": "风景打卡",
        "response_kind": "gps:ambiguous",
        "cost_time": 2.6,
    },
    {
        "user_query": "请告诉我明天实时排队多久",
        "ai_response": "抱歉，这个问题需要实时运营数据支持，我不能根据现有资料编造。",
        "intent_type": "边界问题",
        "sentiment": "中性",
        "focus_point": "实时排队",
        "query_scope": "FACT",
        "matched_attraction": "",
        "recommendation_label": "",
        "response_kind": "refused:unsupported_fact",
        "cost_time": 1.1,
    },
]


def seed_demo_logs(reset: bool = False) -> Dict[str, Any]:
    """Insert deterministic interactions so the admin dashboard is meaningful in demos."""

    db_path = log_service.db_path
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        if reset:
            cursor.execute("DELETE FROM interaction_logs WHERE username = 'demo_visitor'")

        now = datetime.now()
        inserted = 0
        for index, item in enumerate(DEMO_INTERACTIONS):
            created_at = (now - timedelta(minutes=(len(DEMO_INTERACTIONS) - index) * 11)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            cursor.execute(
                """
                INSERT INTO interaction_logs
                (username, user_query, ai_response, intent_type, sentiment, focus_point,
                 query_scope, matched_attraction, recommendation_label, response_kind, cost_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "demo_visitor",
                    item["user_query"],
                    item["ai_response"],
                    item["intent_type"],
                    item["sentiment"],
                    item["focus_point"],
                    item["query_scope"],
                    item["matched_attraction"],
                    item["recommendation_label"],
                    item["response_kind"],
                    item["cost_time"],
                    created_at,
                ),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "db_path": resolve_path("data/processed/interaction_logs.db"),
        "inserted": inserted,
        "reset": reset,
        "username": "demo_visitor",
    }
