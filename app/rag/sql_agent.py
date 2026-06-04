from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import resolve_path
from app.rag.llm_client import generate_chat_completion
from app.rag.response_contract import compact_rows, make_evidence, make_refusal


ANALYTICS_SCHEMA = """
CREATE TABLE tourist_behavior (
  tourist_id TEXT,
  user_nickname TEXT,
  age INTEGER,
  gender TEXT,
  attraction_name TEXT,
  attraction_type TEXT,
  visit_date TEXT,
  stay_duration REAL,
  ticket_cost REAL,
  food_cost REAL,
  shopping_cost REAL,
  transport_cost REAL,
  entertainment_cost REAL,
  total_cost REAL,
  group_size INTEGER,
  satisfaction INTEGER
);
"""

SOURCE_PREFIX = "基于游客行为数据分析，"


@dataclass
class AgeFilter:
    op: str
    lower: Optional[float] = None
    upper: Optional[float] = None


@dataclass
class SemanticQueryPlan:
    metric_key: str
    metric_label: str
    answer_unit: str = ""
    dimension_key: Optional[str] = None
    dimension_label: str = ""
    filters: List[Tuple[str, Any]] = field(default_factory=list)
    query_mode: str = "scalar"
    order: str = "desc"
    limit: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        filters: List[Dict[str, Any]] = []
        for key, value in self.filters:
            if isinstance(value, AgeFilter):
                filters.append(
                    {
                        "key": key,
                        "type": "age_filter",
                        "op": value.op,
                        "lower": value.lower,
                        "upper": value.upper,
                    }
                )
            else:
                filters.append({"key": key, "value": value})
        return {
            "metric_key": self.metric_key,
            "metric_label": self.metric_label,
            "answer_unit": self.answer_unit,
            "dimension_key": self.dimension_key,
            "dimension_label": self.dimension_label,
            "filters": filters,
            "query_mode": self.query_mode,
            "order": self.order,
            "limit": self.limit,
        }


class TouristAnalyticsAgent:
    """Semantic-SQL analytics layer for visitor behavior data."""

    DISALLOWED_SQL = ("insert ", "update ", "delete ", "drop ", "alter ", "pragma ", "attach ")

    METRICS: Dict[str, Dict[str, str]] = {
        "record_count": {"expr": "count(*)", "alias": "record_count", "label": "记录数"},
        "visits": {"expr": "count(*)", "alias": "visits", "label": "访问量"},
        "avg_ticket_cost": {"expr": "round(avg(cast(ticket_cost as real)), 2)", "alias": "avg_ticket_cost", "label": "平均门票消费"},
        "avg_total_cost": {"expr": "round(avg(cast(total_cost as real)), 2)", "alias": "avg_total_cost", "label": "平均总消费"},
        "avg_food_cost": {"expr": "round(avg(cast(food_cost as real)), 2)", "alias": "avg_food_cost", "label": "平均餐饮消费"},
        "avg_shopping_cost": {"expr": "round(avg(cast(shopping_cost as real)), 2)", "alias": "avg_shopping_cost", "label": "平均购物消费"},
        "avg_transport_cost": {"expr": "round(avg(cast(transport_cost as real)), 2)", "alias": "avg_transport_cost", "label": "平均交通消费"},
        "avg_entertainment_cost": {"expr": "round(avg(cast(entertainment_cost as real)), 2)", "alias": "avg_entertainment_cost", "label": "平均娱乐消费"},
        "avg_stay": {"expr": "round(avg(cast(stay_duration as real)), 2)", "alias": "avg_stay", "label": "平均停留时长"},
        "avg_satisfaction": {"expr": "round(avg(cast(satisfaction as real)), 2)", "alias": "avg_satisfaction", "label": "平均满意度"},
        "avg_group_size": {"expr": "round(avg(cast(group_size as real)), 2)", "alias": "avg_group_size", "label": "平均同行人数"},
        "min_age": {"expr": "min(cast(age as real))", "alias": "min_age", "label": "最小年龄"},
        "low_satisfaction_count": {"expr": "count(*)", "alias": "low_satisfaction_count", "label": "低满意度记录数"},
        "high_satisfaction_count": {"expr": "count(*)", "alias": "high_satisfaction_count", "label": "高满意度记录数"},
    }

    DIMENSIONS: Dict[str, Dict[str, str]] = {
        "attraction_name": {"expr": "attraction_name", "alias": "attraction_name", "label": "景点"},
        "attraction_type": {"expr": "attraction_type", "alias": "attraction_type", "label": "景点类型"},
        "gender": {"expr": "gender", "alias": "gender", "label": "性别"},
        "month": {"expr": "substr(visit_date, 1, 7)", "alias": "month", "label": "月份"},
    }

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or resolve_path("data/processed/tourist_behavior.db")
        self._ensure_indices()
        self._domain_cache = self._load_domain_cache()

    def query(self, user_query: str) -> str:
        return self.query_with_trace(user_query)["answer"]

    def query_with_trace(self, user_query: str) -> Dict[str, Any]:
        if self._has_source_conflict(user_query):
            answer = (
                "抱歉，这个问题要求混用错误的数据源。游客行为数据只能用于统计分析，"
                "景区 DOCX 资料只能用于景点事实、历史文化和讲解内容，我不能把一种数据源当作另一种事实依据。"
            )
            return {
                "answer": answer,
                "response_kind": "refused:source_conflict",
                "semantic_plan": None,
                "sql": None,
                "rows_preview": [],
                "evidence": [],
                "warnings": [],
                "refusal": make_refusal(
                    "source_conflict",
                    message="游客行为分析不能直接充当景点事实来源。",
                    suggested_queries=[
                        "请改问游客偏好、消费、停留或满意度分析",
                        "请把景点事实问题单独提出来问",
                    ],
                    allowed_sources=["behavior_sql"],
                ),
                "trace": {"fallback_used": False},
            }

        comparison = self._gender_comparison_response(user_query)
        if comparison:
            return {
                "answer": comparison,
                "response_kind": "analytics:special_case",
                "semantic_plan": {"mode": "gender_comparison"},
                "sql": None,
                "rows_preview": [],
                "evidence": [make_evidence("behavior_sql", "tourist_behavior", snippet=comparison)],
                "warnings": [],
                "refusal": None,
                "trace": {"fallback_used": False, "special_case": True},
            }

        special = self._special_case_response(user_query)
        if special:
            return {
                "answer": special,
                "response_kind": "analytics:special_case",
                "semantic_plan": {"mode": "special_case"},
                "sql": None,
                "rows_preview": [],
                "evidence": [make_evidence("behavior_sql", "tourist_behavior", snippet=special)],
                "warnings": [],
                "refusal": None,
                "trace": {"fallback_used": False, "special_case": True},
            }

        plan = self._plan_semantic_query(user_query)
        if plan:
            sql, params = self._build_sql(plan)
            rows = self.execute_sql(sql, params)
            if not rows:
                return {
                    "answer": f"{SOURCE_PREFIX}暂时没有检索到相关记录。",
                    "response_kind": "analytics:empty",
                    "semantic_plan": plan.to_dict(),
                    "sql": sql,
                    "rows_preview": [],
                    "evidence": [],
                    "warnings": [],
                    "refusal": None,
                    "trace": {"fallback_used": False, "params": list(params)},
                }
            if "error" in rows[0]:
                return {
                    "answer": "抱歉，游客行为数据分析暂时失败，请稍后再试。",
                    "response_kind": "analytics:error",
                    "semantic_plan": plan.to_dict(),
                    "sql": sql,
                    "rows_preview": compact_rows(rows, limit=1),
                    "evidence": [],
                    "warnings": [],
                    "refusal": None,
                    "trace": {"fallback_used": False, "params": list(params)},
                }
            rendered = self._render_semantic_result(plan, rows)
            if rendered:
                sample_count = self._estimate_sample_size(plan)
                warnings = []
                if sample_count is not None and sample_count < 30:
                    warnings.append(f"low_sample_size:{sample_count}")
                return {
                    "answer": rendered,
                    "response_kind": "analytics",
                    "semantic_plan": plan.to_dict(),
                    "sql": sql,
                    "rows_preview": compact_rows(rows),
                    "evidence": [
                        make_evidence(
                            "behavior_sql",
                            "tourist_behavior",
                            field=plan.metric_key,
                            snippet=rendered,
                            metadata={
                                "sql": sql,
                                "sample_count": sample_count,
                                "query_mode": plan.query_mode,
                            },
                        )
                    ],
                    "warnings": warnings,
                    "refusal": None,
                    "trace": {"fallback_used": False, "params": list(params)},
                }

        sql_query = self._generate_sql(user_query)
        if not sql_query:
            return {
                "answer": "抱歉，我暂时无法从游客行为数据中整理出这个问题的分析结果。",
                "response_kind": "analytics:unresolved",
                "semantic_plan": None,
                "sql": None,
                "rows_preview": [],
                "evidence": [],
                "warnings": ["semantic_parse_failed"],
                "refusal": None,
                "trace": {"fallback_used": False},
            }

        result_data = self.execute_sql(sql_query)
        if not result_data:
            return {
                "answer": f"{SOURCE_PREFIX}暂时没有检索到相关记录。",
                "response_kind": "analytics:empty",
                "semantic_plan": None,
                "sql": sql_query,
                "rows_preview": [],
                "evidence": [],
                "warnings": ["llm_sql_fallback"],
                "refusal": None,
                "trace": {"fallback_used": True},
            }
        if "error" in result_data[0]:
            return {
                "answer": "抱歉，游客行为数据分析暂时失败，请稍后再试。",
                "response_kind": "analytics:error",
                "semantic_plan": None,
                "sql": sql_query,
                "rows_preview": compact_rows(result_data, limit=1),
                "evidence": [],
                "warnings": ["llm_sql_fallback"],
                "refusal": None,
                "trace": {"fallback_used": True},
            }
        rendered = self._render_rows_fallback(result_data)
        return {
            "answer": rendered,
            "response_kind": "analytics:fallback",
            "semantic_plan": None,
            "sql": sql_query,
            "rows_preview": compact_rows(result_data),
            "evidence": [
                make_evidence(
                    "behavior_sql",
                    "tourist_behavior",
                    snippet=rendered,
                    metadata={"sql": sql_query},
                )
            ],
            "warnings": ["llm_sql_fallback"],
            "refusal": None,
            "trace": {"fallback_used": True},
        }

    def get_preference_hint(self, attraction_types: List[str]) -> Optional[str]:
        if not attraction_types:
            return None

        placeholders = ",".join("?" for _ in attraction_types)
        sql = (
            "select attraction_type, round(avg(stay_duration), 1) as avg_stay, "
            "round(avg(satisfaction), 2) as avg_satisfaction, count(*) as visits "
            f"from tourist_behavior where attraction_type in ({placeholders}) "
            "group by attraction_type order by visits desc limit 1"
        )
        result = self.execute_sql(sql, attraction_types)
        if not result or "error" in result[0]:
            return None
        top = result[0]
        return (
            f"基于游客行为数据，{top['attraction_type']}类景点通常停留约"
            f"{top['avg_stay']}小时，平均满意度约{top['avg_satisfaction']}分。"
        )

    def execute_sql(self, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
        if not os.path.exists(self.db_path):
            return [{"error": f"Behavior database not found: {self.db_path}"}]
        if not self._is_safe_select(sql):
            return [{"error": "Only safe SELECT analytics queries are allowed."}]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(sql, list(params or []))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            return [{"error": f"SQL execution failed: {exc}"}]
        finally:
            conn.close()

    def _ensure_indices(self) -> None:
        if not os.path.exists(self.db_path):
            return

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            table_exists = cursor.execute(
                "select count(*) from sqlite_master where type='table' and name='tourist_behavior'"
            ).fetchone()[0]
            if not table_exists:
                return
            statements = [
                "create index if not exists idx_tourist_behavior_gender on tourist_behavior(gender)",
                "create index if not exists idx_tourist_behavior_attraction_type on tourist_behavior(attraction_type)",
                "create index if not exists idx_tourist_behavior_attraction_name on tourist_behavior(attraction_name)",
                "create index if not exists idx_tourist_behavior_visit_date on tourist_behavior(visit_date)",
                "create index if not exists idx_tourist_behavior_satisfaction on tourist_behavior(satisfaction)",
            ]
            for statement in statements:
                cursor.execute(statement)
            conn.commit()
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    def _load_domain_cache(self) -> Dict[str, List[str]]:
        cache = {"attraction_types": [], "attraction_names": []}
        if not os.path.exists(self.db_path):
            return cache

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            for key, column in (("attraction_types", "attraction_type"), ("attraction_names", "attraction_name")):
                rows = cursor.execute(
                    f"select distinct {column} from tourist_behavior where {column} is not null and trim({column}) != ''"
                ).fetchall()
                cache[key] = sorted({str(row[0]).strip() for row in rows if str(row[0]).strip()})
        except sqlite3.Error:
            return cache
        finally:
            conn.close()
        return cache

    def _special_case_response(self, user_query: str) -> Optional[str]:
        query = str(user_query or "")

        if "不同人群偏好" in query or "人群偏好差异" in query:
            female = self.execute_sql(
                "select attraction_type, count(*) as visits from tourist_behavior "
                "where gender = '女' group by attraction_type order by visits desc limit 1"
            )
            male = self.execute_sql(
                "select attraction_type, count(*) as visits from tourist_behavior "
                "where gender = '男' group by attraction_type order by visits desc limit 1"
            )
            if female and male and "error" not in female[0] and "error" not in male[0]:
                return (
                    f"{SOURCE_PREFIX}女性游客当前最常选择的类型是{female[0]['attraction_type']}，"
                    f"男性游客当前最常选择的类型是{male[0]['attraction_type']}。"
                    "这说明不同人群在景点偏好上存在明显差异。"
                )

        if "消费趋势" in query:
            total = self.execute_sql("select round(avg(cast(total_cost as real)), 2) as avg_total_cost from tourist_behavior")
            top_type = self.execute_sql(
                "select attraction_type, count(*) as visits from tourist_behavior "
                "group by attraction_type order by visits desc limit 1"
            )
            if total and top_type and "error" not in total[0] and "error" not in top_type[0]:
                return (
                    f"{SOURCE_PREFIX}样本游客的人均总消费约为{total[0]['avg_total_cost']}元，"
                    f"当前出现频次最高的景点类型是{top_type[0]['attraction_type']}。"
                    "这说明游客消费主要集中在高频热门类型景点。"
                )

        if "消费构成" in query or "花费构成" in query:
            rows = self.execute_sql(
                "select "
                "round(avg(cast(ticket_cost as real)), 2) as ticket_cost, "
                "round(avg(cast(transport_cost as real)), 2) as transport_cost, "
                "round(avg(cast(food_cost as real)), 2) as food_cost, "
                "round(avg(cast(shopping_cost as real)), 2) as shopping_cost, "
                "round(avg(cast(entertainment_cost as real)), 2) as entertainment_cost "
                "from tourist_behavior"
            )
            if rows and "error" not in rows[0]:
                ranked = sorted(
                    (
                        ("门票", rows[0].get("ticket_cost")),
                        ("交通", rows[0].get("transport_cost")),
                        ("餐饮", rows[0].get("food_cost")),
                        ("购物", rows[0].get("shopping_cost")),
                        ("娱乐", rows[0].get("entertainment_cost")),
                    ),
                    key=lambda item: float(item[1] or 0),
                    reverse=True,
                )
                parts = [f"{name}{value}元" for name, value in ranked if value is not None]
                if parts:
                    return f"{SOURCE_PREFIX}平均消费构成从高到低依次为：" + "、".join(parts) + "。"

        return None

    def _plan_semantic_query(self, user_query: str) -> Optional[SemanticQueryPlan]:
        query = str(user_query or "")
        lowered = query.lower()
        matched_type = self._match_attraction_type(query)

        if any(term in query for term in ("一共有多少条", "多少条记录", "总记录")):
            metric_key = "record_count"
        elif any(term in query for term in ("一共接待", "总共接待", "接待了多少", "多少游客", "多少人去过", "有多少人", "游客有多少人", "游客一共有多少")):
            metric_key = "visits"
        elif any(term in query for term in ("平均同行人数", "同行人数", "平均团体人数", "几个人一起来", "几个人一起玩", "几人一起")):
            metric_key = "avg_group_size"
        else:
            metric_key = self._detect_metric(query)
        if not metric_key:
            return None

        plan = SemanticQueryPlan(
            metric_key=metric_key,
            metric_label=self.METRICS[metric_key]["label"],
            answer_unit=self._metric_unit(metric_key),
            order=self._detect_order(lowered),
            limit=self._detect_limit(query),
        )

        wants_type_dimension = self._wants_attraction_type_dimension(query)
        wants_attraction_dimension = self._wants_attraction_name_dimension(query)

        if ("每个月" in query or "按月" in query or "月份" in query) and not wants_type_dimension:
            plan.dimension_key = "month"
            plan.dimension_label = "月份"
            plan.query_mode = "time_series" if ("按月" in query or "每个月" in query) else "ranking"
            if "月份" in query and plan.limit is None:
                plan.limit = 1 if any(term in query for term in ("最高", "最低", "最长", "最短")) else 12
        elif any(term in query for term in ("按性别", "性别分布", "男女", "不同性别")):
            plan.dimension_key = "gender"
            plan.dimension_label = "性别"
            plan.query_mode = "grouped"
        elif wants_attraction_dimension:
            plan.dimension_key = "attraction_name"
            plan.dimension_label = "景点"
            plan.query_mode = "ranking"
        elif wants_type_dimension:
            plan.dimension_key = "attraction_type"
            plan.dimension_label = "景点类型"
            plan.query_mode = "ranking" if any(term in query for term in ("前", "排名", "最高", "最多", "最受欢迎", "最火", "最喜欢")) else "grouped"
        elif matched_type and any(term in query for term in ("前", "排名", "哪些景点", "哪几个景点", "最常去", "最高")):
            plan.dimension_key = "attraction_name"
            plan.dimension_label = "景点"
            plan.query_mode = "ranking"
        elif "景点类型" in query or "类型" in query:
            plan.dimension_key = "attraction_type"
            plan.dimension_label = "景点类型"
            plan.query_mode = "grouped"
        elif any(term in query for term in ("访问量最高", "前3个景点", "哪几个景点", "哪些景点")) or (
            "景点" in query and any(term in query for term in ("前", "排名", "最高", "最多", "最常去"))
        ):
            plan.dimension_key = "attraction_name"
            plan.dimension_label = "景点"
            plan.query_mode = "ranking"

        if plan.dimension_key and plan.query_mode == "grouped":
            if any(term in query for term in ("最高", "最低", "最长", "最短", "排名", "前3", "前5", "哪几个")):
                plan.query_mode = "ranking"
            elif plan.limit is None:
                plan.limit = 8

        if plan.dimension_key is None:
            plan.query_mode = "scalar"
            plan.limit = None
        elif plan.query_mode == "ranking" and plan.limit is None:
            plan.limit = 3

        filters = self._detect_filters(query)
        if metric_key == "low_satisfaction_count":
            filters.append(("satisfaction_lt", 3))
        if metric_key == "high_satisfaction_count":
            filters.append(("satisfaction_eq", 5))
        plan.filters = filters

        return plan

    def _detect_metric(self, query: str) -> Optional[str]:
        if "低满意度记录" in query:
            return "low_satisfaction_count"
        if "高满意度记录" in query:
            return "high_satisfaction_count"
        if "满意度" in query:
            return "avg_satisfaction"
        if any(term in query for term in ("最小", "最年轻", "最小孩子")) and any(term in query for term in ("几岁", "年龄", "孩子")):
            return "min_age"
        if any(term in query for term in ("停留", "待多长", "待多久", "逛多久", "一般逛多久")):
            return "avg_stay"
        if any(term in query for term in ("同行", "团体人数", "几个人一起来", "几个人一起玩", "几人一起")):
            return "avg_group_size"
        if "餐饮" in query or "吃饭" in query or "food_cost" in query:
            return "avg_food_cost"
        if "购物" in query:
            return "avg_shopping_cost"
        if "交通" in query:
            return "avg_transport_cost"
        if "娱乐" in query or "玩平均花" in query or "玩花" in query or "玩的花费" in query:
            return "avg_entertainment_cost"
        if any(term in query for term in ("门票", "票价", "票费", "票价消费")):
            return "avg_ticket_cost"
        if any(term in query for term in ("消费", "花费", "总消费")):
            return "avg_total_cost"
        if any(term in query for term in ("访问量", "访问记录", "热门", "偏好", "喜欢", "最受欢迎", "最火", "最多")):
            return "visits"
        return None

    @staticmethod
    def _metric_unit(metric_key: str) -> str:
        if metric_key in {"record_count", "visits", "low_satisfaction_count", "high_satisfaction_count"}:
            return "条"
        if metric_key == "min_age":
            return "岁"
        if metric_key == "avg_group_size":
            return "人"
        if metric_key == "avg_stay":
            return "小时"
        if metric_key == "avg_satisfaction":
            return "分"
        return "元" if "cost" in metric_key else ""

    @staticmethod
    def _detect_order(query: str) -> str:
        if any(term in query for term in ("最低", "最短", "最少")):
            return "asc"
        return "desc"

    @staticmethod
    def _detect_limit(query: str) -> Optional[int]:
        number_match = re.search(r"(?:前\s*)?([1-9]\d?)\s*(?:个|类|种|名)", query)
        if number_match:
            return int(number_match.group(1))
        if "前5" in query or "前五" in query:
            return 5
        if "前8" in query:
            return 8
        if any(term in query for term in ("前3", "前三", "哪几个", "排名")):
            return 3
        return None

    def _detect_filters(self, query: str) -> List[Tuple[str, Any]]:
        filters: List[Tuple[str, Any]] = []

        if any(term in query for term in ("女性", "女游客", "女的", "女生")):
            filters.append(("gender", "女"))
        elif any(term in query for term in ("男性", "男游客", "男的", "男生")):
            filters.append(("gender", "男"))

        age_range_match = re.search(r"(\d{1,2})\s*(?:到|-|至)\s*(\d{1,2})岁", query)
        age_gte_match = re.search(r"(\d{1,2})岁(?:及)?以上", query)
        age_lte_match = re.search(r"(\d{1,2})岁(?:及)?以下", query)

        if age_range_match:
            lower, upper = age_range_match.groups()
            filters.append(("age_between", AgeFilter("between", float(lower), float(upper))))
        elif age_gte_match:
            filters.append(("age_gte", AgeFilter(">=", float(age_gte_match.group(1)))))
        elif age_lte_match:
            filters.append(("age_lte", AgeFilter("<=", upper=float(age_lte_match.group(1)))))
        elif "20到30岁" in query:
            filters.append(("age_between", AgeFilter("between", 20, 30)))
        elif "31到45岁" in query:
            filters.append(("age_between", AgeFilter("between", 31, 45)))
        elif "46岁以上" in query:
            filters.append(("age_gte", AgeFilter(">=", 46)))
        elif "30岁以下" in query:
            filters.append(("age_lt", AgeFilter("<", upper=30)))
        elif "50岁以上" in query:
            filters.append(("age_gt", AgeFilter(">", lower=50)))

        if "上半年" in query:
            filters.append(("date_range", ("2025-01-01", "2025-07-01")))
        elif "下半年" in query:
            filters.append(("date_range", ("2025-07-01", "2026-01-01")))
        else:
            month_match = re.search(r"2025\s*年\s*(\d{1,2})\s*月", query)
            if month_match:
                month = int(month_match.group(1))
                if 1 <= month <= 12:
                    start = f"2025-{month:02d}-01"
                    end = f"2025-{month + 1:02d}-01" if month < 12 else "2026-01-01"
                    filters.append(("date_range", (start, end)))

        matched_type = self._match_attraction_type(query)
        if matched_type:
            filters.append(("attraction_type", matched_type))

        matched_name = self._match_known_value(query, self._domain_cache["attraction_names"])
        if matched_name:
            filters.append(("attraction_name", matched_name))

        return filters

    def _build_sql(self, plan: SemanticQueryPlan) -> Tuple[str, List[Any]]:
        metric = self.METRICS[plan.metric_key]
        params: List[Any] = []
        where_clauses: List[str] = []

        for filter_key, value in plan.filters:
            if filter_key == "gender":
                where_clauses.append("gender = ?")
                params.append(value)
            elif filter_key == "attraction_type":
                where_clauses.append("attraction_type = ?")
                params.append(value)
            elif filter_key == "attraction_name":
                where_clauses.append("attraction_name = ?")
                params.append(value)
            elif filter_key == "date_range":
                where_clauses.append("visit_date >= ? and visit_date < ?")
                params.extend(list(value))
            elif filter_key == "age_between":
                where_clauses.append("cast(age as real) between ? and ?")
                params.extend([value.lower, value.upper])
            elif filter_key == "age_gte":
                where_clauses.append("cast(age as real) >= ?")
                params.append(value.lower)
            elif filter_key == "age_gt":
                where_clauses.append("cast(age as real) > ?")
                params.append(value.lower)
            elif filter_key == "age_lt":
                where_clauses.append("cast(age as real) < ?")
                params.append(value.upper)
            elif filter_key == "age_lte":
                where_clauses.append("cast(age as real) <= ?")
                params.append(value.upper)
            elif filter_key == "satisfaction_lt":
                where_clauses.append("cast(satisfaction as real) < ?")
                params.append(value)
            elif filter_key == "satisfaction_eq":
                where_clauses.append("cast(satisfaction as real) = ?")
                params.append(value)

        select_parts = [f"{metric['expr']} as {metric['alias']}"]
        group_by_clause = ""
        order_by_clause = ""
        limit_clause = ""

        if plan.dimension_key:
            dimension = self.DIMENSIONS[plan.dimension_key]
            select_parts.insert(0, f"{dimension['expr']} as {dimension['alias']}")
            group_by_clause = f" group by {dimension['alias']}"
            if plan.query_mode == "time_series":
                order_by_clause = f" order by {dimension['alias']}"
            else:
                order_by_clause = f" order by {metric['alias']} {plan.order}"
            if plan.limit:
                limit_clause = f" limit {int(plan.limit)}"
        sql = "select " + ", ".join(select_parts) + " from tourist_behavior"
        if where_clauses:
            sql += " where " + " and ".join(where_clauses)
        sql += group_by_clause
        if not plan.dimension_key and plan.metric_key == "avg_satisfaction" and plan.query_mode == "scalar":
            sql += ""
        sql += order_by_clause + limit_clause
        return sql, params

    def _estimate_sample_size(self, plan: SemanticQueryPlan) -> Optional[int]:
        _, params = self._build_sql(plan)
        where_clauses: List[str] = []
        for filter_key, value in plan.filters:
            if filter_key == "gender":
                where_clauses.append("gender = ?")
            elif filter_key == "attraction_type":
                where_clauses.append("attraction_type = ?")
            elif filter_key == "attraction_name":
                where_clauses.append("attraction_name = ?")
            elif filter_key == "date_range":
                where_clauses.append("visit_date >= ? and visit_date < ?")
            elif filter_key == "age_between":
                where_clauses.append("cast(age as real) between ? and ?")
            elif filter_key == "age_gte":
                where_clauses.append("cast(age as real) >= ?")
            elif filter_key == "age_gt":
                where_clauses.append("cast(age as real) > ?")
            elif filter_key == "age_lt":
                where_clauses.append("cast(age as real) < ?")
            elif filter_key == "age_lte":
                where_clauses.append("cast(age as real) <= ?")
            elif filter_key == "satisfaction_lt":
                where_clauses.append("cast(satisfaction as real) < ?")
            elif filter_key == "satisfaction_eq":
                where_clauses.append("cast(satisfaction as real) = ?")
        count_sql = "select count(*) as sample_count from tourist_behavior"
        if where_clauses:
            count_sql += " where " + " and ".join(where_clauses)
        rows = self.execute_sql(count_sql, params)
        if not rows or "error" in rows[0]:
            return None
        try:
            return int(rows[0].get("sample_count") or 0)
        except (TypeError, ValueError):
            return None

    def _render_semantic_result(self, plan: SemanticQueryPlan, rows: List[Dict[str, Any]]) -> Optional[str]:
        if not rows or "error" in rows[0]:
            return None

        metric_alias = self.METRICS[plan.metric_key]["alias"]
        unit = self._metric_unit(plan.metric_key)

        if plan.query_mode == "scalar":
            value = rows[0].get(metric_alias)
            return f"{SOURCE_PREFIX}{plan.metric_label}约为{value}{unit}。"

        if plan.query_mode == "time_series":
            parts = [f"{row['month']}：{row[metric_alias]}{unit}" for row in rows]
            return f"{SOURCE_PREFIX}{plan.metric_label}按月变化为：" + "；".join(parts) + "。"

        name_key = self.DIMENSIONS[plan.dimension_key]["alias"] if plan.dimension_key else "name"
        if plan.dimension_key == "gender":
            parts = [f"{row[name_key]}：{row[metric_alias]}{unit}" for row in rows]
            return f"{SOURCE_PREFIX}{plan.metric_label}按性别分布为：" + "；".join(parts) + "。"

        parts = []
        for index, row in enumerate(rows[: plan.limit or len(rows)], start=1):
            parts.append(f"{index}. {row[name_key]}（{plan.metric_label}{row[metric_alias]}{unit}）")
        if not parts:
            return None
        if plan.query_mode == "grouped" and (plan.limit or 0) >= 8:
            return f"{SOURCE_PREFIX}" + "；".join(parts) + "。"
        return f"{SOURCE_PREFIX}" + "；".join(parts) + "。"

    def _render_rows_fallback(self, rows: List[Dict[str, Any]]) -> str:
        row = rows[0]
        if len(row) == 1:
            key, value = next(iter(row.items()))
            return f"{SOURCE_PREFIX}{key}为{value}。"

        display_limit = 5 if len(rows) >= 5 else len(rows)
        parts = []
        for index, item in enumerate(rows[:display_limit], start=1):
            rendered = "，".join(f"{key}={value}" for key, value in item.items())
            parts.append(f"{index}. {rendered}")
        return f"{SOURCE_PREFIX}" + "；".join(parts) + "。"

    def _generate_sql(self, user_query: str) -> Optional[str]:
        system_prompt = (
            "You are a SQLite analytics assistant. Use only tourist_behavior. "
            "Never infer scenic facts such as opening hours, location or attraction history. "
            "Return one SQLite SELECT statement only."
        )
        prompt = f"""
Schema:
{ANALYTICS_SCHEMA}

User question: {user_query}

Rules:
- Use only tourist_behavior.
- Use LIKE '%keyword%' for fuzzy matching when needed.
- Use visit_date for date filters.
- Use satisfaction for satisfaction-related analysis.
- Use total_cost and related cost fields for spending analysis.
- attraction_type and attraction_name are behavior labels, not scenic facts.
- Output a single SELECT statement.
"""
        sql_query = generate_chat_completion(
            prompt,
            system_prompt,
            temperature=0.1,
            max_tokens=220,
            return_error_text=False,
        )
        if not sql_query:
            return None
        cleaned = sql_query.replace("```sql", "").replace("```sqlite", "").replace("```", "").strip()
        return cleaned if self._is_safe_select(cleaned) else None

    def _has_source_conflict(self, query: str) -> bool:
        docx_terms = ("docx", "DOCX", "景区介绍文档", "介绍文档", "景区文档", "资料文档")
        behavior_terms = ("行为数据", "游客消费数据", "游客行为 Excel", "游客行为数据")
        behavior_metric_terms = (
            "消费",
            "满意度",
            "访问量",
            "平均",
            "统计",
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
        fact_metric_terms = ("开放时间", "官方开放", "门票价格", "票价", "佛体", "玄奘", "历史", "文化内涵")
        has_behavior_metric = any(term in query for term in behavior_metric_terms)
        if any(term in query for term in docx_terms) and any(term in query for term in behavior_metric_terms):
            return True
        if "官方" in query and any(term in query for term in behavior_terms) and any(term in query for term in fact_metric_terms):
            return True
        if any(term in query for term in behavior_terms) and any(term in query for term in fact_metric_terms) and not has_behavior_metric:
            return True
        if "当作" in query and any(term in query for term in ("门票", "票价", "开放时间", "文化内涵")):
            return True
        return False

    def _is_safe_select(self, sql: str) -> bool:
        normalized = re.sub(r"\s+", " ", sql.strip().lower())
        if not normalized.startswith("select "):
            return False
        if any(token in normalized for token in self.DISALLOWED_SQL):
            return False
        if " tourist_behavior" not in normalized and "from tourist_behavior" not in normalized:
            return False
        if " attractions" in normalized:
            return False
        return True

    def _contains_known_type(self, query: str) -> bool:
        return bool(self._match_attraction_type(query))

    def _gender_comparison_response(self, user_query: str) -> Optional[str]:
        query = str(user_query or "")
        if not ("男" in query and "女" in query and any(term in query for term in ("多还是", "谁多", "哪个多"))):
            return None
        matched_type = self._match_attraction_type(query)
        if not matched_type:
            return None
        rows = self.execute_sql(
            "select gender, count(*) as visits from tourist_behavior "
            "where attraction_type = ? group by gender order by visits desc",
            [matched_type],
        )
        if not rows or "error" in rows[0]:
            return None
        counts = {str(row.get("gender")): row.get("visits") for row in rows}
        male = counts.get("男", 0)
        female = counts.get("女", 0)
        winner = "女" if female > male else "男" if male > female else "男女一样多"
        comparison = "女的多" if winner == "女" else "男的多" if winner == "男" else winner
        return f"{SOURCE_PREFIX}去{matched_type}的人里，男游客{male}条，女游客{female}条，{comparison}。"

    @staticmethod
    def _wants_attraction_type_dimension(query: str) -> bool:
        type_dimension_terms = (
            "哪类景点",
            "哪种景点",
            "哪5种景点",
            "哪五种景点",
            "哪些类型",
            "哪几类",
            "景点类型",
            "类型排名",
            "前5类",
            "前五类",
            "5种景点类型",
            "前5种",
            "前五种",
            "最喜欢的前",
            "最火的",
            "最受欢迎",
            "去的人最多",
        )
        return any(term in query for term in type_dimension_terms)

    @staticmethod
    def _wants_attraction_name_dimension(query: str) -> bool:
        if any(term in query for term in ("景点类型", "哪类景点", "哪种景点", "哪5种景点", "哪五种景点", "哪些类型", "哪几类")):
            return False
        name_dimension_terms = (
            "哪5个景点",
            "哪五个景点",
            "哪几个景点",
            "哪些景点",
            "哪个景点",
            "前5名",
            "前五名",
            "去的人最多",
        )
        return any(term in query for term in name_dimension_terms)

    def _match_attraction_type(self, query: str) -> Optional[str]:
        normalized_query = self._normalize_type_text(query)
        for value in sorted(self._domain_cache["attraction_types"], key=len, reverse=True):
            if not value:
                continue
            normalized_value = self._normalize_type_text(value)
            if value in query or normalized_value in normalized_query:
                return value
        return None

    @staticmethod
    def _normalize_type_text(value: str) -> str:
        return (
            str(value or "")
            .replace("和", "与")
            .replace("及", "与")
            .replace("类", "")
            .replace("的", "")
            .replace("景点", "")
            .replace(" ", "")
        )

    @staticmethod
    def _match_known_value(query: str, candidates: Sequence[str]) -> Optional[str]:
        for value in sorted(candidates, key=len, reverse=True):
            if value and value in query:
                return value
        return None


TouristSQLAgent = TouristAnalyticsAgent
