from __future__ import annotations

import os
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import resolve_path
from app.rag.llm_client import generate_chat_completion, llm_is_configured
from app.rag.rule_config import load_json_config, term_tuple
from app.rag.response_contract import compact_rows, make_evidence, make_refusal


SOURCE_PREFIX = "基于游客行为数据分析，"

_LOW_SAMPLE_THRESHOLD = 30

SQL_SEMANTIC_RULE_CONFIG = load_json_config("app/rag/config/sql_semantic_rules.json")


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
    planner_source: str = "deterministic"
    confidence: float = 0.8
    reasoning: List[str] = field(default_factory=list)

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
            "planner_source": self.planner_source,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
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
        "avg_age": {"expr": "round(avg(cast(age as real)), 2)", "alias": "avg_age", "label": "平均年龄"},
        "min_age": {"expr": "min(cast(age as real))", "alias": "min_age", "label": "最小年龄"},
        "max_age": {"expr": "max(cast(age as real))", "alias": "max_age", "label": "最大年龄"},
        "distinct_attractions": {
            "expr": "count(distinct attraction_name)",
            "alias": "distinct_attractions",
            "label": "景点数量",
        },
        "distinct_attraction_types": {
            "expr": "count(distinct attraction_type)",
            "alias": "distinct_attraction_types",
            "label": "景点类型数量",
        },
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

    @staticmethod
    def _sql_result(
        answer: str,
        response_kind: str,
        *,
        semantic_plan: Any = None,
        sql: Optional[str] = None,
        rows_preview: Optional[List[Dict[str, Any]]] = None,
        evidence: Optional[List[Any]] = None,
        warnings: Optional[List[str]] = None,
        refusal: Any = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "answer": answer,
            "response_kind": response_kind,
            "semantic_plan": semantic_plan,
            "sql": sql,
            "rows_preview": rows_preview or [],
            "evidence": evidence or [],
            "warnings": warnings or [],
            "refusal": refusal,
            "trace": trace or {},
        }

    def query_with_trace(self, user_query: str) -> Dict[str, Any]:
        if self._has_source_conflict(user_query):
            answer = (
                "抱歉，这个问题要求混用错误的数据源。游客行为数据只能用于统计分析，"
                "景区资料只能用于景点事实、历史文化和讲解内容，我不能把一种数据源当作另一种事实依据。"
            )
            return self._sql_result(
                answer,
                "refused:source_conflict",
                refusal=make_refusal(
                    "source_conflict",
                    message="游客行为分析不能直接充当景点事实来源。",
                    suggested_queries=[
                        "请改问游客偏好、消费、停留或满意度分析",
                        "请把景点事实问题单独提出来问",
                    ],
                    allowed_sources=["behavior_sql"],
                ),
                trace={"fallback_used": False},
            )

        comparison = self._gender_comparison_response(user_query)
        if comparison:
            return self._sql_result(
                comparison,
                "analytics:special_case",
                semantic_plan={"mode": "gender_comparison"},
                evidence=[make_evidence("behavior_sql", "tourist_behavior", snippet=comparison)],
                trace={"fallback_used": False, "special_case": True},
            )

        special = self._special_case_response(user_query)
        if special:
            return self._sql_result(
                special,
                "analytics:special_case",
                semantic_plan={"mode": "special_case"},
                evidence=[make_evidence("behavior_sql", "tourist_behavior", snippet=special)],
                trace={"fallback_used": False, "special_case": True},
            )

        plan, plan_warnings = self._plan_analytics_query(user_query)
        if plan:
            sql, params = self._build_sql(plan)
            rows = self.execute_sql(sql, params)
            if not rows:
                return self._sql_result(
                    f"{SOURCE_PREFIX}暂时没有检索到相关记录。",
                    "analytics:empty",
                    semantic_plan=plan.to_dict(),
                    sql=sql,
                    warnings=plan_warnings,
                    trace={"fallback_used": bool(plan_warnings), "params": list(params)},
                )
            if "error" in rows[0]:
                return self._sql_result(
                    "抱歉，游客行为数据分析暂时失败，请稍后再试。",
                    "analytics:error",
                    semantic_plan=plan.to_dict(),
                    sql=sql,
                    rows_preview=compact_rows(rows, limit=1),
                    warnings=plan_warnings,
                    trace={"fallback_used": bool(plan_warnings), "params": list(params)},
                )
            rendered = self._render_semantic_result(plan, rows)
            if rendered:
                sample_count = self._estimate_sample_size(plan)
                warnings = list(plan_warnings)
                if sample_count is not None and sample_count < _LOW_SAMPLE_THRESHOLD:
                    warnings.append(f"low_sample_size:{sample_count}")
                return self._sql_result(
                    rendered,
                    "analytics",
                    semantic_plan=plan.to_dict(),
                    sql=sql,
                    rows_preview=compact_rows(rows),
                    evidence=[
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
                    warnings=warnings,
                    trace={"fallback_used": bool(plan_warnings), "params": list(params)},
                )

        return self._sql_result(
            "抱歉，我暂时无法从游客行为数据中整理出这个问题的分析结果。",
            "analytics:unresolved",
            warnings=plan_warnings or ["semantic_parse_failed"],
            trace={"fallback_used": bool(plan_warnings)},
        )

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

    def _plan_analytics_query(self, user_query: str) -> Tuple[Optional[SemanticQueryPlan], List[str]]:
        semantic_agent_plan = self._plan_with_semantic_agent(user_query)
        if semantic_agent_plan:
            return semantic_agent_plan, []
        if llm_is_configured():
            return None, ["analytics_semantic_agent_failed"]

        deterministic_plan = self._plan_semantic_query(user_query)
        if deterministic_plan:
            deterministic_plan.planner_source = "deterministic_fallback"
            deterministic_plan.reasoning = deterministic_plan.reasoning or [
                "Analytics semantic agent was unavailable or returned an invalid plan; used deterministic fallback."
            ]
            return deterministic_plan, ["analytics_semantic_agent_fallback"]

        return None, ["semantic_parse_failed"]

    def _plan_with_semantic_agent(self, user_query: str) -> Optional[SemanticQueryPlan]:
        if not llm_is_configured():
            return None

        metrics = {
            key: {
                "label": spec["label"],
                "unit": self._metric_unit(key),
            }
            for key, spec in self.METRICS.items()
        }
        dimensions = {
            key: spec["label"]
            for key, spec in self.DIMENSIONS.items()
        }
        system_prompt = (
            "You are an analytics semantic-planning sub-agent. "
            "Convert a Chinese tourist-behavior analytics question into strict JSON only. "
            "Do not write SQL and do not answer the question."
        )
        prompt = (
            "Return one JSON object with these fields:\n"
            "- metric_key: one allowed metric key.\n"
            "- dimension_key: attraction_name, attraction_type, gender, month, or null.\n"
            "- query_mode: scalar, grouped, ranking, or time_series.\n"
            "- order: desc or asc.\n"
            "- limit: integer or null.\n"
            "- filters: array of objects. Allowed filters: "
            '{"key":"gender","value":"男|女"}, '
            '{"key":"attraction_type","value":"..."}, '
            '{"key":"attraction_name","value":"..."}, '
            '{"key":"date_range","start":"YYYY-MM-DD","end":"YYYY-MM-DD"}, '
            '{"key":"age_between","lower":20,"upper":30}, '
            '{"key":"age_gte","lower":46}, '
            '{"key":"age_lte","upper":30}.\n'
            "- confidence: 0.0 to 1.0.\n"
            "- reasoning: short Chinese sentence.\n\n"
            f"Allowed metrics: {json.dumps(metrics, ensure_ascii=False)}\n"
            f"Allowed dimensions: {json.dumps(dimensions, ensure_ascii=False)}\n"
            f"Known attraction types: {json.dumps(self._domain_cache.get('attraction_types', [])[:80], ensure_ascii=False)}\n"
            f"Known attraction names: {json.dumps(self._domain_cache.get('attraction_names', [])[:120], ensure_ascii=False)}\n\n"
            "Examples:\n"
            '游客平均在景区花多少钱？ => {"metric_key":"avg_total_cost","dimension_key":null,"query_mode":"scalar","order":"desc","limit":null,"filters":[],"confidence":0.94,"reasoning":"询问样本游客平均总消费。"}\n'
            '哪5种景点去的人最多？ => {"metric_key":"visits","dimension_key":"attraction_type","query_mode":"ranking","order":"desc","limit":5,"filters":[],"confidence":0.92,"reasoning":"按景点类型统计访问量排行。"}\n'
            '女性游客平均餐饮消费是多少？ => {"metric_key":"avg_food_cost","dimension_key":null,"query_mode":"scalar","order":"desc","limit":null,"filters":[{"key":"gender","value":"女"}],"confidence":0.9,"reasoning":"筛选女性游客并计算餐饮均值。"}\n'
            '女游客玩平均花多少？ => {"metric_key":"avg_entertainment_cost","dimension_key":null,"query_mode":"scalar","order":"desc","limit":null,"filters":[{"key":"gender","value":"女"}],"confidence":0.9,"reasoning":"筛选女性游客并计算娱乐/游玩花费均值。"}\n'
            '2025年4月玩的花费平均多少？ => {"metric_key":"avg_entertainment_cost","dimension_key":null,"query_mode":"scalar","order":"desc","limit":null,"filters":[{"key":"date_range","start":"2025-04-01","end":"2025-05-01"}],"confidence":0.9,"reasoning":"询问2025年4月娱乐/游玩花费均值，date_range 采用左闭右开区间。"}\n\n'
            '样本游客平均年龄是多少？ => {"metric_key":"avg_age","dimension_key":null,"query_mode":"scalar","order":"desc","limit":null,"filters":[],"confidence":0.9,"reasoning":"询问平均年龄。"}\n'
            '游客最大年龄是多少？ => {"metric_key":"max_age","dimension_key":null,"query_mode":"scalar","order":"desc","limit":null,"filters":[],"confidence":0.9,"reasoning":"询问最大年龄。"}\n'
            '一共涵盖了多少个景点？ => {"metric_key":"distinct_attractions","dimension_key":null,"query_mode":"scalar","order":"desc","limit":null,"filters":[],"confidence":0.9,"reasoning":"询问去重景点数量。"}\n\n'
            f"User question: {user_query}\n"
            "JSON only."
        )
        raw = generate_chat_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.0,
            max_tokens=420,
            return_error_text=False,
            json_mode=True,
        )
        payload = self._parse_semantic_agent_json(raw)
        if not payload:
            return None
        return self._plan_from_semantic_agent_payload(payload)

    @staticmethod
    def _parse_semantic_agent_json(raw: str) -> Optional[Dict[str, Any]]:
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

    def _plan_from_semantic_agent_payload(
        self,
        payload: Dict[str, Any],
    ) -> Optional[SemanticQueryPlan]:
        metric_key = str(payload.get("metric_key") or "").strip()
        if metric_key not in self.METRICS:
            return None

        dimension_key = payload.get("dimension_key")
        if dimension_key in ("", "null", "None"):
            dimension_key = None
        if dimension_key is not None:
            dimension_key = str(dimension_key).strip()
            if dimension_key not in self.DIMENSIONS:
                return None

        query_mode = str(payload.get("query_mode") or "scalar").strip()
        if query_mode not in {"scalar", "grouped", "ranking", "time_series"}:
            query_mode = "ranking" if dimension_key else "scalar"
        if not dimension_key:
            query_mode = "scalar"

        order = str(payload.get("order") or "desc").strip().lower()
        if order not in {"asc", "desc"}:
            order = "desc"

        limit = self._coerce_limit(payload.get("limit"))
        if not dimension_key:
            limit = None
        elif query_mode == "ranking" and limit is None:
            limit = 3
        elif query_mode == "grouped" and limit is None:
            limit = 8

        filters = self._coerce_semantic_agent_filters(payload.get("filters"))
        if filters is None:
            return None

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
            reasoning = ["Analytics semantic sub-agent produced a structured plan."]

        return SemanticQueryPlan(
            metric_key=metric_key,
            metric_label=self.METRICS[metric_key]["label"],
            answer_unit=self._metric_unit(metric_key),
            dimension_key=dimension_key,
            dimension_label=self.DIMENSIONS[dimension_key]["label"] if dimension_key else "",
            filters=filters,
            query_mode=query_mode,
            order=order,
            limit=limit,
            planner_source="analytics_semantic_agent",
            confidence=confidence,
            reasoning=reasoning,
        )

    @staticmethod
    def _coerce_limit(value: Any) -> Optional[int]:
        if value in (None, "", "null", "None"):
            return None
        try:
            limit = int(value)
        except (TypeError, ValueError):
            return None
        if limit <= 0:
            return None
        return min(limit, 20)

    def _coerce_semantic_agent_filters(self, raw_filters: Any) -> Optional[List[Tuple[str, Any]]]:
        if raw_filters in (None, "", "null"):
            return []
        if not isinstance(raw_filters, list):
            return None

        filters: List[Tuple[str, Any]] = []
        for item in raw_filters:
            if not isinstance(item, dict):
                return None
            key = str(item.get("key") or "").strip()
            if not key:
                continue

            if key == "gender":
                value = self._normalize_gender_filter(item.get("value"))
                if not value:
                    return None
                filters.append(("gender", value))
            elif key == "attraction_type":
                value = self._match_known_value(str(item.get("value") or ""), self._domain_cache["attraction_types"])
                if not value:
                    return None
                filters.append(("attraction_type", value))
            elif key == "attraction_name":
                value = self._match_known_value(str(item.get("value") or ""), self._domain_cache["attraction_names"])
                if not value:
                    return None
                filters.append(("attraction_name", value))
            elif key == "date_range":
                start = str(item.get("start") or "").strip()
                end = str(item.get("end") or "").strip()
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
                    return None
                end = self._normalize_exclusive_date_end(start, end)
                filters.append(("date_range", (start, end)))
            elif key == "age_between":
                try:
                    lower = float(item.get("lower"))
                    upper = float(item.get("upper"))
                except (TypeError, ValueError):
                    return None
                filters.append(("age_between", AgeFilter("between", lower, upper)))
            elif key in {"age_gte", "age_gt"}:
                try:
                    lower = float(item.get("lower"))
                except (TypeError, ValueError):
                    return None
                filters.append((key, AgeFilter(">=" if key == "age_gte" else ">", lower=lower)))
            elif key in {"age_lte", "age_lt"}:
                try:
                    upper = float(item.get("upper"))
                except (TypeError, ValueError):
                    return None
                filters.append((key, AgeFilter("<=" if key == "age_lte" else "<", upper=upper)))
            else:
                return None
        return filters

    @staticmethod
    def _normalize_exclusive_date_end(start: str, end: str) -> str:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d").date()
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            return end
        if end_date <= start_date or end_date.day == 1:
            return end
        return (end_date + timedelta(days=1)).isoformat()

    @staticmethod
    def _normalize_gender_filter(value: Any) -> Optional[str]:
        text = str(value or "").strip()
        if text in {"女", "女性", "女生", "female", "Female"}:
            return "女"
        if text in {"男", "男性", "男生", "male", "Male"}:
            return "男"
        return None

    def _plan_semantic_query(self, user_query: str) -> Optional[SemanticQueryPlan]:
        query = str(user_query or "")
        lowered = query.lower()
        matched_type = self._match_attraction_type(query)

        if any(term in query for term in ("一共有多少条", "多少条记录", "总记录")):
            metric_key = "record_count"
        elif any(term in query for term in ("多少个景点", "涵盖了多少个景点", "景点数量")):
            metric_key = "distinct_attractions"
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

    @staticmethod
    def _matches_semantic_rule(query: str, rule: Dict[str, Any]) -> bool:
        include_all = [str(item) for item in rule.get("include_all") or [] if str(item)]
        if include_all and not all(term in query for term in include_all):
            return False

        include_any = [str(item) for item in rule.get("include_any") or [] if str(item)]
        if include_any and not any(term in query for term in include_any):
            return False

        include_any_groups = rule.get("include_any_groups") or []
        if include_any_groups:
            for group in include_any_groups:
                terms = [str(item) for item in group or [] if str(item)]
                if terms and not any(term in query for term in terms):
                    return False

        exclude_any = [str(item) for item in rule.get("exclude_any") or [] if str(item)]
        if exclude_any and any(term in query for term in exclude_any):
            return False

        return True

    def _detect_metric(self, query: str) -> Optional[str]:
        metric_rules = SQL_SEMANTIC_RULE_CONFIG.get("metric_rules") or []
        if isinstance(metric_rules, list):
            for rule in metric_rules:
                if not isinstance(rule, dict):
                    continue
                metric_key = str(rule.get("metric") or "").strip()
                if metric_key and self._matches_semantic_rule(query, rule):
                    return metric_key

        if "低满意度记录" in query:
            return "low_satisfaction_count"
        if "高满意度记录" in query:
            return "high_satisfaction_count"
        if "满意度" in query:
            return "avg_satisfaction"
        if any(term in query for term in ("平均年龄", "年龄平均", "平均多大", "平均多大年纪", "平均年纪", "一般多大年纪", "一般多大")):
            return "avg_age"
        if any(term in query for term in ("最大年龄", "年龄最大", "最大年纪", "最高年龄", "最年长", "年纪最大")):
            return "max_age"
        if any(term in query for term in ("最小", "最年轻", "最小孩子")) and any(term in query for term in ("几岁", "年龄", "孩子")):
            return "min_age"
        if any(term in query for term in ("停留", "待多长", "待多久", "逛多久", "一般逛多久")):
            return "avg_stay"
        if any(term in query for term in ("多少种景点类型", "多少类景点", "几种景点类型", "景点类型多少", "包含了多少种景点类型")):
            return "distinct_attraction_types"
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
        if any(term in query for term in ("消费", "花费", "花多少", "花多少钱", "多少钱", "开销", "总消费")):
            return "avg_total_cost"
        if any(term in query for term in ("访问量", "访问记录", "热门", "偏好", "喜欢", "最受欢迎", "最火", "最多")):
            return "visits"
        return None

    @staticmethod
    def _metric_unit(metric_key: str) -> str:
        if metric_key in {"record_count", "visits", "low_satisfaction_count", "high_satisfaction_count"}:
            return "条"
        if metric_key == "distinct_attraction_types":
            return "种"
        if metric_key in {"avg_age", "min_age", "max_age"}:
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

    @staticmethod
    def _filter_clause(filter_key: str, value: Any) -> Tuple[str, List[Any]]:
        _MAP: Dict[str, Tuple[str, Any]] = {
            "gender":           ("gender = ?",                          lambda v: [v]),
            "attraction_type":  ("attraction_type = ?",                 lambda v: [v]),
            "attraction_name":  ("attraction_name = ?",                 lambda v: [v]),
            "date_range":       ("visit_date >= ? and visit_date < ?",  list),
            "age_between":      ("cast(age as real) between ? and ?",   lambda v: [v.lower, v.upper]),
            "age_gte":          ("cast(age as real) >= ?",              lambda v: [v.lower]),
            "age_gt":           ("cast(age as real) > ?",               lambda v: [v.lower]),
            "age_lt":           ("cast(age as real) < ?",               lambda v: [v.upper]),
            "age_lte":          ("cast(age as real) <= ?",              lambda v: [v.upper]),
            "satisfaction_lt":  ("cast(satisfaction as real) < ?",      lambda v: [v]),
            "satisfaction_eq":  ("cast(satisfaction as real) = ?",      lambda v: [v]),
        }
        if filter_key not in _MAP:
            return "", []
        tpl, extractor = _MAP[filter_key]
        return tpl, extractor(value)

    def _build_sql(self, plan: SemanticQueryPlan) -> Tuple[str, List[Any]]:
        metric = self.METRICS[plan.metric_key]
        params: List[Any] = []
        where_clauses: List[str] = []

        for filter_key, value in plan.filters:
            clause, clause_params = self._filter_clause(filter_key, value)
            if clause:
                where_clauses.append(clause)
                params.extend(clause_params)

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
        sql += order_by_clause + limit_clause
        return sql, params

    def _estimate_sample_size(self, plan: SemanticQueryPlan) -> Optional[int]:
        _, params = self._build_sql(plan)
        where_clauses: List[str] = []
        for filter_key, value in plan.filters:
            clause, _ = self._filter_clause(filter_key, value)
            if clause:
                where_clauses.append(clause)
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
            return f"{SOURCE_PREFIX}{plan.metric_label}约为{self._format_metric_value(value)}{unit}。"

        if plan.query_mode == "time_series":
            parts = [f"{row['month']}：{self._format_metric_value(row[metric_alias])}{unit}" for row in rows]
            return f"{SOURCE_PREFIX}{plan.metric_label}按月变化为：" + "；".join(parts) + "。"

        name_key = self.DIMENSIONS[plan.dimension_key]["alias"] if plan.dimension_key else "name"
        if plan.dimension_key == "gender":
            parts = [f"{row[name_key]}：{self._format_metric_value(row[metric_alias])}{unit}" for row in rows]
            return f"{SOURCE_PREFIX}{plan.metric_label}按性别分布为：" + "；".join(parts) + "。"

        parts = []
        for index, row in enumerate(rows[: plan.limit or len(rows)], start=1):
            parts.append(f"{index}. {row[name_key]}（{plan.metric_label}{self._format_metric_value(row[metric_alias])}{unit}）")
        if not parts:
            return None
        if plan.query_mode == "grouped" and (plan.limit or 0) >= 8:
            return f"{SOURCE_PREFIX}" + "；".join(parts) + "。"
        return f"{SOURCE_PREFIX}" + "；".join(parts) + "。"

    @staticmethod
    def _format_metric_value(value: Any) -> str:
        if isinstance(value, int):
            return str(value)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        return f"{number:.2f}".rstrip("0").rstrip(".")

    def _has_source_conflict(self, query: str) -> bool:
        if any(term in query for term in ("手机号", "真实姓名", "家庭住址", "住址", "家住", "地址")):
            return True
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
        if any(term in query for term in ("当作", "当成", "说成", "当")) and any(
            term in query for term in ("门票", "票价", "开放时间", "文化内涵")
        ):
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
        type_dimension_terms = term_tuple(
            SQL_SEMANTIC_RULE_CONFIG,
            "dimension_rules",
            "attraction_type_include_any",
            fallback=(
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
            ),
        )
        return any(term in query for term in type_dimension_terms)

    @staticmethod
    def _wants_attraction_name_dimension(query: str) -> bool:
        if any(
            term in query
            for term in term_tuple(
                SQL_SEMANTIC_RULE_CONFIG,
                "dimension_rules",
                "attraction_name_exclude_any",
                fallback=("景点类型", "哪类景点", "哪种景点", "哪5种景点", "哪五种景点", "哪些类型", "哪几类"),
            )
        ):
            return False
        name_dimension_terms = term_tuple(
            SQL_SEMANTIC_RULE_CONFIG,
            "dimension_rules",
            "attraction_name_include_any",
            fallback=("哪5个景点", "哪五个景点", "哪几个景点", "哪些景点", "哪个景点", "前5名", "前五名", "去的人最多"),
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
        normalized_query = TouristAnalyticsAgent._normalize_type_text(query)
        for value in sorted(candidates, key=len, reverse=True):
            if value and value in query:
                return value
            normalized_value = TouristAnalyticsAgent._normalize_type_text(value)
            if normalized_value and normalized_value in normalized_query:
                return value
            if normalized_query and len(normalized_query) >= 3 and normalized_query in normalized_value:
                return value
        return None
