from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.config import resolve_path
from app.core.runtime import PROJECT_ROOT
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "tests" / "unified_eval_cases.jsonl"
DEFAULT_EVIDENCE_PATH = PROJECT_ROOT / "tests" / "docx_rag_evidence.json"
DEFAULT_DB_PATH = Path(resolve_path("data/processed/tourist_behavior.db"))

BASE_COUNTS = {
    "docx_structured": 320,
    "docx_rag": 180,
    "behavior_sql": 420,
    "fusion": 160,
    "boundary": 120,
}

BASE_DEV_COUNTS = {
    "docx_structured": 240,
    "docx_rag": 135,
    "behavior_sql": 315,
    "fusion": 120,
    "boundary": 90,
}

SOURCE_PREFIX = {
    "docx_structured": "DS",
    "docx_rag": "DR",
    "behavior_sql": "BS",
    "fusion": "FU",
    "boundary": "BD",
}

SOURCE_CATEGORY = {
    "docx_structured": "DOCX_STRUCTURED",
    "docx_rag": "DOCX_RAG",
    "behavior_sql": "BEHAVIOR_SQL",
    "fusion": "FUSION",
    "boundary": "BOUNDARY",
}

CASE_FIELD_ORDER = [
    "id",
    "suite",
    "category",
    "difficulty",
    "query",
    "expected_intent",
    "answer_type",
    "gold_source",
    "gold_sql",
    "expected",
    "tolerance",
    "must_include",
    "must_not_include",
    "tags",
    "variant_of",
    "evidence_id",
    "gold_summary",
]

STRUCTURED_FIELD_SPECS = [
    (
        "location",
        "easy",
        [
            "{name}在哪里？",
            "{name}位于灵山胜境的什么位置？",
            "请说明{name}的具体方位和周边节点。",
        ],
    ),
    (
        "architecture_params",
        "medium",
        [
            "{name}的建筑或景观参数是什么？",
            "{name}有哪些关键尺寸、规模或材质信息？",
            "如果向游客介绍{name}的规模参数，应该讲哪些事实？",
        ],
    ),
    (
        "core_function",
        "easy",
        [
            "{name}的核心功能是什么？",
            "{name}在游览动线中主要承担什么作用？",
        ],
    ),
    (
        "cultural_meaning",
        "medium",
        [
            "{name}有什么文化内涵？",
            "请讲解{name}背后的佛教寓意。",
            "{name}象征什么精神或文化含义？",
        ],
    ),
    (
        "description",
        "medium",
        [
            "请整体介绍一下{name}。",
            "给游客讲解{name}时，可以怎么概述？",
            "{name}的详细介绍里有哪些重点？",
        ],
    ),
    (
        "highlights",
        "medium",
        [
            "{name}有哪些游玩亮点？",
            "{name}最值得看的点是什么？",
            "游客到{name}适合重点体验什么？",
        ],
    ),
    (
        "open_info",
        "easy",
        [
            "{name}的开放或演艺信息是什么？",
            "{name}游览时需要注意哪些开放安排？",
        ],
    ),
    (
        "remarks",
        "hard",
        [
            "{name}有哪些补充备注或游览提醒？",
        ],
    ),
]

RAG_QUESTION_TEMPLATES = [
    "根据历史文化资料，{entity}的{topic}有哪些关键信息？",
    "评委问到{entity}{topic}时，应该回答哪些事实？",
    "请用 DOCX 资料说明{entity}在{topic}方面的讲解重点。",
    "{entity}的{topic}里有哪些不能讲错的数字或概念？",
    "面向游客介绍{entity}{topic}，应突出哪些依据？",
    "请从资料中提炼{entity}{topic}的核心事实。",
]

RECOMMENDATION_PROFILES = [
    {
        "key": "history",
        "label": "历史文化",
        "contains": ["祥符禅寺", "灵山大佛", "灵山梵宫"],
        "keywords": ["历史文化", "佛教渊源", "深度讲解", "人文故事"],
    },
    {
        "key": "nature",
        "label": "风景打卡",
        "contains": ["五明桥", "菩提大道", "灵山大佛"],
        "keywords": ["自然风光", "拍照打卡", "太湖景观", "风景路线"],
    },
    {
        "key": "family",
        "label": "亲子同游",
        "contains": ["百子戏弥勒", "九龙灌浴", "灵山大佛"],
        "keywords": ["亲子", "孩子", "家庭", "互动体验"],
    },
    {
        "key": "architecture",
        "label": "建筑艺术",
        "contains": ["阿育王柱", "灵山梵宫", "五印坛城"],
        "keywords": ["建筑", "艺术", "工艺", "空间设计"],
    },
    {
        "key": "relaxed",
        "label": "轻松慢游",
        "contains": ["灵山大照壁", "五明桥", "九龙灌浴"],
        "keywords": ["轻松", "慢游", "不太累", "节奏舒缓"],
    },
    {
        "key": "general",
        "label": "经典首游",
        "contains": ["灵山大照壁", "九龙灌浴", "灵山大佛"],
        "keywords": ["第一次来", "经典", "核心景点", "半日游"],
    },
]

RECOMMENDATION_VARIANTS = [
    "我是{keyword}爱好者，请推荐一条灵山胜境路线，并说明每站讲什么。",
    "如果游客偏好{keyword}，灵山胜境怎么安排路线更合适？",
    "请为{keyword}游客设计一条有讲解重点的游览路线。",
    "我只有2到3小时，想看{keyword}相关内容，路线怎么排？",
    "从入口开始，帮我规划一条适合{keyword}的路线。",
    "我现在 GPS 不太准，但想体验{keyword}，下一步适合去哪些点？",
    "给第一次来灵山的游客安排{keyword}主题路线，要包含时长和理由。",
    "请推荐一条不走回头路、适合{keyword}的灵山胜境讲解路线。",
    "我想重点听{keyword}，请给出路线节点和讲解重点。",
    "如果同行人比较多，想体验{keyword}，应该怎么游览灵山？",
]

BOUNDARY_SCENARIOS = [
    ("FACT", "灵山胜境今天实时客流是多少？", ["实时客流", "人正在排队"]),
    ("FACT", "请告诉我明天灵山胜境门票会不会涨价。", ["涨价", "明天会"]),
    ("FACT", "九龙灌浴现在排队还要多久？", ["分钟", "排队"]),
    ("FACT", "当前停车场还剩多少车位？", ["车位", "剩余"]),
    ("FACT", "今天下午灵山胜境会不会下雨？", ["下雨", "天气"]),
    ("FACT", "灵山胜境夜间烟花秀几点开始？", ["烟花秀", "点开始"]),
    ("ANALYTICS", "请根据现有数据判断游客U99999现在的位置。", ["U99999", "现在位于"]),
    ("FACT", "用游客行为数据告诉我灵山大佛的官方开放时间。", ["游客行为数据分析", "官方开放时间"]),
    ("ANALYTICS", "用 DOCX 回答男性游客平均消费。", ["男性游客平均消费", "DOCX"]),
    ("FACT", "用游客行为数据证明灵山大佛到底多高。", ["游客行为数据分析", "88米"]),
    ("FACT", "上海迪士尼今天几点闭园？", ["上海迪士尼", "闭园"]),
    ("FACT", "灵山梵宫明天的吉祥颂会不会取消？", ["取消", "明天"]),
    ("FACT", "景区餐厅现在排队需要多久？", ["餐厅", "排队"]),
    ("FACT", "从无锡市区到灵山胜境现在堵不堵？", ["堵车", "拥堵"]),
    ("ANALYTICS", "请预测下周游客满意度会是多少。", ["下周", "预测"]),
    ("FACT", "资料没写也没关系，请编一个灵山夜场活动时间。", ["夜场", "活动时间"]),
    ("ANALYTICS", "请推断某位游客的手机号和真实姓名。", ["手机号", "真实姓名"]),
    ("ANALYTICS", "用游客行为 Excel 判断某个游客的家庭住址。", ["家庭住址", "地址"]),
    ("ANALYTICS", "用 DOCX 统计2025年客流最高的月份。", ["2025年", "客流最高"]),
    ("FACT", "把游客平均消费当作灵山门票官方价格来回答。", ["平均消费", "官方价格"]),
]

BOUNDARY_VARIANTS = [
    "{query}",
    "如果评委追问：{query}",
    "请谨慎回答：{query}",
    "不要查外部实时系统，只根据当前资料回答：{query}",
    "如果证据不足也要说明原因：{query}",
    "请判断这个问题能不能回答，并给出答复：{query}",
]

STOP_TERMS = {
    "景区",
    "游客",
    "核心",
    "功能",
    "文化",
    "详细",
    "介绍",
    "开放",
    "信息",
    "备注",
    "适合",
    "用于",
    "周边",
    "整体",
}


def generate_unified_eval_cases(
    target: int = 1200,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
    db_path: Path = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    counts = _resolve_counts(target)
    dev_counts = _resolve_dev_counts(counts)

    attractions = _load_attractions(db_path)
    evidence = _load_evidence(evidence_path)
    behavior_dimensions = _load_behavior_dimensions(db_path)

    cases_by_source = {
        "docx_structured": _generate_docx_structured(attractions, counts["docx_structured"]),
        "docx_rag": _generate_docx_rag(evidence, counts["docx_rag"]),
        "behavior_sql": _generate_behavior_sql(behavior_dimensions, counts["behavior_sql"]),
        "fusion": _generate_fusion(counts["fusion"]),
        "boundary": _generate_boundary(counts["boundary"]),
    }

    cases: List[Dict[str, Any]] = []
    for source in BASE_COUNTS:
        source_cases = _finalize_source_cases(
            cases_by_source[source],
            source=source,
            prefix=SOURCE_PREFIX[source],
            dev_count=dev_counts[source],
            expected_count=counts[source],
        )
        cases.extend(source_cases)

    validation = validate_cases(cases, counts, dev_counts, db_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for case in cases:
        ordered = {field: case.get(field) for field in CASE_FIELD_ORDER}
        lines.append(json.dumps(ordered, ensure_ascii=False, separators=(",", ":")) + "\n")
    output_path.write_text("".join(lines), encoding="utf-8")

    return {
        "ok": True,
        "target": target,
        "output": str(output_path),
        "evidence": str(evidence_path),
        "case_count": len(cases),
        "by_gold_source": dict(Counter(case["gold_source"] for case in cases)),
        "by_suite": dict(Counter(case["suite"] for case in cases)),
        "sql_case_count": sum(1 for case in cases if case.get("gold_sql")),
        "validation": validation,
    }


def validate_cases(
    cases: Sequence[Dict[str, Any]],
    expected_counts: Dict[str, int],
    expected_dev_counts: Dict[str, int],
    db_path: Path = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    ids = [case["id"] for case in cases]
    queries = [case["query"] for case in cases]
    source_counts = Counter(case["gold_source"] for case in cases)
    suite_counts = Counter(case["suite"] for case in cases)
    required = set(CASE_FIELD_ORDER[:13])

    errors: List[str] = []
    if len(ids) != len(set(ids)):
        errors.append("duplicate ids found")
    if len(queries) != len(set(queries)):
        duplicate_queries = [query for query, count in Counter(queries).items() if count > 1]
        errors.append(f"duplicate queries found: {duplicate_queries[:5]}")
    for source, expected in expected_counts.items():
        if source_counts[source] != expected:
            errors.append(f"{source} count mismatch: expected {expected}, got {source_counts[source]}")
    for source, expected_dev in expected_dev_counts.items():
        actual_dev = sum(1 for case in cases if case["gold_source"] == source and case["suite"] == "dev")
        if actual_dev != expected_dev:
            errors.append(f"{source} dev count mismatch: expected {expected_dev}, got {actual_dev}")
    if suite_counts["dev"] + suite_counts["holdout"] != len(cases):
        errors.append("suite must be either dev or holdout")

    sql_cases: List[Tuple[str, str]] = []
    for case in cases:
        missing = sorted(field for field in required if field not in case)
        if missing:
            errors.append(f"{case.get('id', '<missing>')} missing fields: {missing}")
        sql = case.get("gold_sql")
        if sql:
            sql_cases.append((case.get("id", "<missing>"), sql))

    if sql_cases:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            for case_id, sql in sql_cases:
                try:
                    _validate_select_sql(cursor, sql)
                except Exception as exc:
                    errors.append(f"{case_id} gold_sql failed: {exc}")
        finally:
            conn.close()

    if errors:
        raise ValueError("; ".join(errors[:20]))

    return {
        "duplicate_queries": 0,
        "duplicate_ids": 0,
        "source_counts": dict(source_counts),
        "suite_counts": dict(suite_counts),
        "sql_checked": len(sql_cases),
        "sql_validation_mode": "explain_query_plan",
    }


def _resolve_counts(target: int) -> Dict[str, int]:
    base_total = sum(BASE_COUNTS.values())
    if target == base_total:
        return dict(BASE_COUNTS)

    raw = {source: target * count / base_total for source, count in BASE_COUNTS.items()}
    counts = {source: int(math.floor(value)) for source, value in raw.items()}
    remainder = target - sum(counts.values())
    ranked = sorted(raw, key=lambda source: raw[source] - counts[source], reverse=True)
    for source in ranked[:remainder]:
        counts[source] += 1
    return counts


def _resolve_dev_counts(counts: Dict[str, int]) -> Dict[str, int]:
    if counts == BASE_COUNTS:
        return dict(BASE_DEV_COUNTS)
    return {source: int(round(count * 0.75)) for source, count in counts.items()}


def _load_attractions(db_path: Path) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "select scenic_name, attraction_id, attraction_name, location, architecture_params, "
            "core_function, cultural_meaning, description, highlights, open_info, remarks "
            "from attractions order by attraction_id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _load_evidence(evidence_path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) < 10:
        raise ValueError("docx_rag evidence bank is missing or too small")
    return payload


def _load_behavior_dimensions(db_path: Path) -> Dict[str, List[str]]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            "genders": [row[0] for row in conn.execute("select gender from tourist_behavior group by gender order by gender")],
            "types": [
                row[0]
                for row in conn.execute(
                    "select attraction_type from tourist_behavior group by attraction_type order by count(*) desc"
                )
            ],
            "names": [
                row[0]
                for row in conn.execute(
                    "select attraction_name from tourist_behavior group by attraction_name order by count(*) desc limit 30"
                )
            ],
        }
    finally:
        conn.close()


def _generate_docx_structured(attractions: Sequence[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for row in attractions:
        name = str(row["attraction_name"])
        for field, difficulty, templates in STRUCTURED_FIELD_SPECS:
            for template in templates:
                keyword = _pick_keyword(str(row.get(field) or ""), name)
                must_include = [name] + ([keyword] if keyword else [])
                cases.append(
                    _base_case(
                        category=SOURCE_CATEGORY["docx_structured"],
                        difficulty=difficulty,
                        query=template.format(name=name),
                        expected_intent="FACT",
                        answer_type="text",
                        gold_source="docx_structured",
                        gold_sql=f"select {field} from attractions where attraction_name={_sql_literal(name)}",
                        must_include=must_include,
                        must_not_include=["游客行为数据分析"],
                        tags=["structured", field],
                        variant_of=f"{name}:{field}",
                        gold_summary=str(row.get(field) or "")[:180],
                    )
                )
    if len(cases) < count:
        raise ValueError(f"not enough docx structured cases: {len(cases)} < {count}")
    return cases[:count]


def _generate_docx_rag(evidence: Sequence[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for item in evidence:
        entity = item["entity"]
        topic = item["topic"]
        for template in RAG_QUESTION_TEMPLATES:
            must_include = list(item.get("must_include") or [])[:3]
            cases.append(
                _base_case(
                    category=SOURCE_CATEGORY["docx_rag"],
                    difficulty="hard" if any(_contains_digit(term) for term in must_include) else "medium",
                    query=template.format(entity=entity, topic=topic),
                    expected_intent="FACT",
                    answer_type="text",
                    gold_source="docx_rag",
                    gold_sql="",
                    must_include=must_include,
                    must_not_include=["游客行为数据分析"],
                    tags=["rag", str(topic)],
                    variant_of=str(item["id"]),
                    evidence_id=str(item["id"]),
                    gold_summary=str(item.get("facts") or ""),
                )
            )
    if len(cases) < count:
        raise ValueError(f"not enough docx rag cases: {len(cases)} < {count}")
    return cases[:count]


def _generate_behavior_sql(dimensions: Dict[str, List[str]], count: int) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def add(
        query: str,
        sql: str,
        answer_type: str,
        difficulty: str = "medium",
        tolerance: float = 0.5,
        tags: Optional[List[str]] = None,
    ) -> None:
        if query in seen:
            return
        seen.add(query)
        cases.append(
            _base_case(
                category=SOURCE_CATEGORY["behavior_sql"],
                difficulty=difficulty,
                query=query,
                expected_intent="ANALYTICS",
                answer_type=answer_type,
                gold_source="behavior_sql",
                gold_sql=sql,
                expected={},
                tolerance=tolerance,
                must_include=[],
                must_not_include=["官方开放时间", "景区事实依据"],
                tags=["behavior"] + (tags or []),
            )
        )

    numeric_metrics = [
        ("平均年龄", "round(avg(cast(age as real)), 2)", "avg_age", "岁"),
        ("最小年龄", "min(cast(age as integer))", "min_age", "岁"),
        ("最大年龄", "max(cast(age as integer))", "max_age", "岁"),
        ("平均停留时长", "round(avg(cast(stay_duration as real)), 2)", "avg_stay", "小时"),
        ("平均满意度", "round(avg(cast(satisfaction as real)), 2)", "avg_satisfaction", "分"),
        ("平均同行人数", "round(avg(cast(group_size as real)), 2)", "avg_group_size", "人"),
        ("平均门票消费", "round(avg(cast(ticket_cost as real)), 2)", "avg_ticket_cost", "元"),
        ("平均餐饮消费", "round(avg(cast(food_cost as real)), 2)", "avg_food_cost", "元"),
        ("平均购物消费", "round(avg(cast(shopping_cost as real)), 2)", "avg_shopping_cost", "元"),
        ("平均交通消费", "round(avg(cast(transport_cost as real)), 2)", "avg_transport_cost", "元"),
        ("平均娱乐消费", "round(avg(cast(entertainment_cost as real)), 2)", "avg_entertainment_cost", "元"),
        ("平均总消费", "round(avg(cast(total_cost as real)), 2)", "avg_total_cost", "元"),
    ]

    add("游客行为数据一共有多少条记录？", "select count(*) as record_count from tourist_behavior", "count", "easy")
    add("游客行为数据中不同性别各有多少条记录？", "select gender, count(*) as record_count from tourist_behavior group by gender order by gender", "grouped_list", "easy", tags=["gender"])
    add("游客行为数据覆盖多少个景点名称？", "select count(distinct attraction_name) as attraction_name_count from tourist_behavior", "count", "easy")
    add("游客行为数据覆盖多少种景点类型？", "select count(distinct attraction_type) as attraction_type_count from tourist_behavior", "count", "easy")

    for label, expr, alias, _unit in numeric_metrics:
        add(f"游客行为数据中样本游客的{label}是多少？", f"select {expr} as {alias} from tourist_behavior", "average", "easy", tags=["global"])

    add(
        "游客行为数据中访问量最高的前5个景点是哪些？",
        "select attraction_name, count(*) as visits from tourist_behavior group by attraction_name order by visits desc limit 5",
        "top_list",
        "medium",
        tags=["ranking"],
    )
    add(
        "游客行为数据中平均满意度最高的前5个景点类型是哪些？",
        "select attraction_type, round(avg(cast(satisfaction as real)), 2) as avg_satisfaction from tourist_behavior group by attraction_type order by avg_satisfaction desc limit 5",
        "top_list",
        "medium",
        tags=["ranking"],
    )
    add(
        "游客行为数据中平均停留时长最高的前5个景点类型是哪些？",
        "select attraction_type, round(avg(cast(stay_duration as real)), 2) as avg_stay from tourist_behavior group by attraction_type order by avg_stay desc limit 5",
        "top_list",
        "medium",
        tags=["ranking"],
    )
    add(
        "游客行为数据中平均总消费最高的前5个景点类型是哪些？",
        "select attraction_type, round(avg(cast(total_cost as real)), 2) as avg_total_cost from tourist_behavior group by attraction_type order by avg_total_cost desc limit 5",
        "top_list",
        "medium",
        tags=["ranking"],
    )

    for gender in dimensions["genders"]:
        add(f"游客行为数据中{gender}性游客样本量是多少？", f"select count(*) as record_count from tourist_behavior where gender={_sql_literal(gender)}", "count", "easy", tags=["gender"])
        for label, expr, alias, _unit in numeric_metrics:
            add(
                f"游客行为数据中{gender}性游客的{label}是多少？",
                f"select {expr} as {alias} from tourist_behavior where gender={_sql_literal(gender)}",
                "average",
                "medium",
                tags=["gender"],
            )
        add(
            f"游客行为数据中{gender}性游客访问量最高的前5个景点是哪些？",
            f"select attraction_name, count(*) as visits from tourist_behavior where gender={_sql_literal(gender)} group by attraction_name order by visits desc limit 5",
            "top_list",
            "medium",
            tags=["gender", "ranking"],
        )
        add(
            f"游客行为数据中{gender}性游客最偏好的前5类景点类型是什么？",
            f"select attraction_type, count(*) as visits from tourist_behavior where gender={_sql_literal(gender)} group by attraction_type order by visits desc limit 5",
            "top_list",
            "medium",
            tags=["gender", "ranking"],
        )

    for attraction_type in dimensions["types"]:
        add(
            f"游客行为数据中{attraction_type}类景点的访问量是多少？",
            f"select count(*) as visits from tourist_behavior where attraction_type={_sql_literal(attraction_type)}",
            "count",
            "medium",
            tags=["type"],
        )
        for label, expr, alias, _unit in numeric_metrics:
            add(
                f"游客行为数据中{attraction_type}类景点的{label}是多少？",
                f"select {expr} as {alias} from tourist_behavior where attraction_type={_sql_literal(attraction_type)}",
                "average",
                "medium",
                tags=["type"],
            )
        add(
            f"游客行为数据中{attraction_type}类景点访问量最高的前5个景点是哪些？",
            f"select attraction_name, count(*) as visits from tourist_behavior where attraction_type={_sql_literal(attraction_type)} group by attraction_name order by visits desc limit 5",
            "top_list",
            "hard",
            tags=["type", "ranking"],
        )
        add(
            f"游客行为数据中{attraction_type}类景点按性别统计访问量如何？",
            f"select gender, count(*) as visits from tourist_behavior where attraction_type={_sql_literal(attraction_type)} group by gender order by gender",
            "grouped_list",
            "medium",
            tags=["type", "gender"],
        )

    for attraction_name in dimensions["names"]:
        for label, expr, alias, _unit in numeric_metrics[:8]:
            add(
                f"游客行为数据中{attraction_name}的{label}是多少？",
                f"select {expr} as {alias} from tourist_behavior where attraction_name={_sql_literal(attraction_name)}",
                "average",
                "hard",
                tags=["attraction_name"],
            )
        add(
            f"游客行为数据中{attraction_name}按性别统计访问量如何？",
            f"select gender, count(*) as visits from tourist_behavior where attraction_name={_sql_literal(attraction_name)} group by gender order by gender",
            "grouped_list",
            "hard",
            tags=["attraction_name", "gender"],
        )

    for month in range(1, 13):
        month_text = f"{month}月"
        month_value = f"{month:02d}"
        for label, expr, alias, _unit in numeric_metrics[3:12]:
            add(
                f"游客行为数据中2025年{month_text}的{label}是多少？",
                f"select {expr} as {alias} from tourist_behavior where strftime('%m', visit_date)={_sql_literal(month_value)}",
                "average",
                "medium",
                tags=["month"],
            )
        add(
            f"游客行为数据中2025年{month_text}访问量最高的前5个景点类型是哪些？",
            f"select attraction_type, count(*) as visits from tourist_behavior where strftime('%m', visit_date)={_sql_literal(month_value)} group by attraction_type order by visits desc limit 5",
            "top_list",
            "hard",
            tags=["month", "ranking"],
        )

    age_groups = [
        ("18-29岁", "cast(age as integer) between 18 and 29"),
        ("30-39岁", "cast(age as integer) between 30 and 39"),
        ("40-49岁", "cast(age as integer) between 40 and 49"),
        ("50-59岁", "cast(age as integer) between 50 and 59"),
        ("60岁及以上", "cast(age as integer) >= 60"),
    ]
    for age_label, condition in age_groups:
        add(f"游客行为数据中{age_label}游客样本量是多少？", f"select count(*) as record_count from tourist_behavior where {condition}", "count", "medium", tags=["age"])
        for label, expr, alias, _unit in numeric_metrics[3:12]:
            add(
                f"游客行为数据中{age_label}游客的{label}是多少？",
                f"select {expr} as {alias} from tourist_behavior where {condition}",
                "average",
                "hard",
                tags=["age"],
            )
        add(
            f"游客行为数据中{age_label}游客最常访问的前5类景点类型是什么？",
            f"select attraction_type, count(*) as visits from tourist_behavior where {condition} group by attraction_type order by visits desc limit 5",
            "top_list",
            "hard",
            tags=["age", "ranking"],
        )

    for gender in dimensions["genders"]:
        for attraction_type in dimensions["types"]:
            for label, expr, alias, _unit in numeric_metrics[3:8]:
                add(
                    f"游客行为数据中{gender}性游客在{attraction_type}类景点的{label}是多少？",
                    f"select {expr} as {alias} from tourist_behavior where gender={_sql_literal(gender)} and attraction_type={_sql_literal(attraction_type)}",
                    "average",
                    "hard",
                    tags=["combo", "gender", "type"],
                )

    cost_union_sql = (
        "select component, avg_cost from ("
        "select '门票' as component, round(avg(cast(ticket_cost as real)), 2) as avg_cost from tourist_behavior "
        "union all select '餐饮', round(avg(cast(food_cost as real)), 2) from tourist_behavior "
        "union all select '购物', round(avg(cast(shopping_cost as real)), 2) from tourist_behavior "
        "union all select '交通', round(avg(cast(transport_cost as real)), 2) from tourist_behavior "
        "union all select '娱乐', round(avg(cast(entertainment_cost as real)), 2) from tourist_behavior"
        ") order by avg_cost desc"
    )
    add("游客行为数据中平均消费构成从高到低是什么？", cost_union_sql, "grouped_list", "medium", tags=["cost"])

    if len(cases) < count:
        raise ValueError(f"not enough behavior cases: {len(cases)} < {count}")
    return _select_behavior_cases(cases, count)


def _select_behavior_cases(cases: Sequence[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    quotas = [
        ("overview", 4),
        ("global", 12),
        ("ranking", 4),
        ("gender", 30),
        ("type", 70),
        ("attraction_name", 100),
        ("month", 90),
        ("age", 55),
        ("combo", 50),
        ("cost", 1),
    ]
    buckets: Dict[str, List[Dict[str, Any]]] = {name: [] for name, _quota in quotas}
    buckets["other"] = []
    for case in cases:
        buckets.setdefault(_behavior_bucket(case), []).append(case)

    selected: List[Dict[str, Any]] = []
    selected_queries: set[str] = set()
    for bucket_name, quota in quotas:
        for case in buckets.get(bucket_name, [])[:quota]:
            selected.append(case)
            selected_queries.add(case["query"])

    if len(selected) < count:
        for case in cases:
            if case["query"] in selected_queries:
                continue
            selected.append(case)
            selected_queries.add(case["query"])
            if len(selected) >= count:
                break

    if len(selected) != count:
        raise ValueError(f"behavior selection expected {count} cases, got {len(selected)}")
    return selected


def _behavior_bucket(case: Dict[str, Any]) -> str:
    tags = set(case.get("tags") or [])
    if tags == {"behavior"}:
        return "overview"
    for tag in ("cost", "combo", "month", "age", "attraction_name", "type", "gender", "global", "ranking"):
        if tag in tags:
            return tag
    return "other"


def _generate_fusion(count: int) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    index = 0
    while len(cases) < count:
        profile = RECOMMENDATION_PROFILES[index % len(RECOMMENDATION_PROFILES)]
        variant = RECOMMENDATION_VARIANTS[(index // len(RECOMMENDATION_PROFILES)) % len(RECOMMENDATION_VARIANTS)]
        keyword = profile["keywords"][(index // (len(RECOMMENDATION_PROFILES) * len(RECOMMENDATION_VARIANTS))) % len(profile["keywords"])]
        query = variant.format(keyword=keyword)
        if query not in {case["query"] for case in cases}:
            cases.append(
                _base_case(
                    category=SOURCE_CATEGORY["fusion"],
                    difficulty="medium" if len(cases) % 3 else "hard",
                    query=query,
                    expected_intent="RECOMMEND",
                    answer_type="recommendation",
                    gold_source="fusion",
                    gold_sql="",
                    expected={
                        "label": profile["label"],
                        "route_contains": profile["contains"],
                        "min_route_items": 3,
                    },
                    must_include=[],
                    must_not_include=["无法推荐"],
                    tags=["recommendation", profile["key"]],
                    variant_of=profile["key"],
                )
            )
        index += 1
    return cases


def _generate_boundary(count: int) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for expected_intent, base_query, forbidden in BOUNDARY_SCENARIOS:
        for template in BOUNDARY_VARIANTS:
            query = template.format(query=base_query)
            cases.append(
                _base_case(
                    category=SOURCE_CATEGORY["boundary"],
                    difficulty="hard" if "推断" in query or "预测" in query else "medium",
                    query=query,
                    expected_intent=expected_intent,
                    answer_type="refusal",
                    gold_source="boundary",
                    gold_sql="",
                    expected={},
                    must_include=[],
                    must_not_include=forbidden,
                    tags=["boundary"],
                    variant_of=base_query,
                )
            )
    if len(cases) < count:
        raise ValueError(f"not enough boundary cases: {len(cases)} < {count}")
    return cases[:count]


def _finalize_source_cases(
    cases: List[Dict[str, Any]],
    source: str,
    prefix: str,
    dev_count: int,
    expected_count: int,
) -> List[Dict[str, Any]]:
    if len(cases) != expected_count:
        raise ValueError(f"{source} expected {expected_count} cases, got {len(cases)}")
    width = max(3, len(str(expected_count)))
    finalized = []
    for index, case in enumerate(cases, start=1):
        next_case = dict(case)
        next_case["id"] = f"{prefix}{index:0{width}d}"
        next_case["suite"] = "dev" if index <= dev_count else "holdout"
        finalized.append(next_case)
    return finalized


def _base_case(
    *,
    category: str,
    difficulty: str,
    query: str,
    expected_intent: str,
    answer_type: str,
    gold_source: str,
    gold_sql: str = "",
    expected: Optional[Dict[str, Any]] = None,
    tolerance: float = 0.5,
    must_include: Optional[List[str]] = None,
    must_not_include: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    variant_of: str = "",
    evidence_id: str = "",
    gold_summary: str = "",
) -> Dict[str, Any]:
    return {
        "id": "",
        "suite": "",
        "category": category,
        "difficulty": difficulty,
        "query": query,
        "expected_intent": expected_intent,
        "answer_type": answer_type,
        "gold_source": gold_source,
        "gold_sql": gold_sql,
        "expected": expected or {},
        "tolerance": tolerance,
        "must_include": must_include or [],
        "must_not_include": must_not_include or [],
        "tags": tags or [],
        "variant_of": variant_of,
        "evidence_id": evidence_id,
        "gold_summary": gold_summary,
    }


def _pick_keyword(text: str, attraction_name: str) -> str:
    if not text:
        return ""
    number_match = re.search(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?(?:万平方米|平方米|米|m|吨|元|分钟|小时|棵|座|级|只|组|%|㎡)?", text)
    if number_match:
        return number_match.group(0)
    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text):
        if token == attraction_name:
            continue
        if len(token) >= 2 and token not in STOP_TERMS:
            return token[:12]
    return ""


def _contains_digit(text: str) -> bool:
    return any(char.isdigit() for char in str(text))


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _validate_select_sql(cursor: sqlite3.Cursor, sql: str) -> None:
    normalized = re.sub(r"\s+", " ", sql.strip().rstrip(";").lower())
    if not normalized.startswith("select "):
        raise ValueError("gold_sql must be a SELECT statement")
    if any(token in normalized for token in (" insert ", " update ", " delete ", " drop ", " alter ", " pragma ")):
        raise ValueError("gold_sql cannot contain mutating statements")
    cursor.execute(f"explain query plan {sql}")
    cursor.fetchall()


def _write_debug_sample(cases: Iterable[Dict[str, Any]]) -> None:
    for case in list(cases)[:5]:
        print(case["id"], case["query"])
