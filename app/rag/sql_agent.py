import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

from app.core.config import resolve_path
from app.rag.llm_client import generate_chat_completion


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


class TouristAnalyticsAgent:
    """Use cross-scenic visitor behavior data only for analytics and preference hints."""

    DISALLOWED_SQL = ("insert ", "update ", "delete ", "drop ", "alter ", "pragma ", "attach ")

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or resolve_path("data/processed/tourist_behavior.db")

    def query(self, user_query: str) -> str:
        rule_based = self._rule_based_response(user_query)
        if rule_based:
            return rule_based

        sql_query = self._generate_sql(user_query)
        if not sql_query:
            return "抱歉，我暂时无法从游客行为数据中整理出这个问题的分析结果。"

        result_data = self.execute_sql(sql_query)
        if not result_data:
            return "基于当前游客行为数据分析，暂时没有检索到相关记录。"
        if "error" in result_data[0]:
            return "抱歉，游客行为数据分析暂时失败，请稍后再试。"

        return self._summarize_result(user_query, result_data)

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

    def execute_sql(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        if not os.path.exists(self.db_path):
            return [{"error": f"Behavior database not found: {self.db_path}"}]
        if not self._is_safe_select(sql):
            return [{"error": "Only safe SELECT analytics queries are allowed."}]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params or [])
            return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            return [{"error": f"SQL execution failed: {exc}"}]
        finally:
            conn.close()

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
        sql_query = generate_chat_completion(prompt, system_prompt, temperature=0.1)
        if not sql_query:
            return None
        cleaned = sql_query.replace("```sql", "").replace("```sqlite", "").replace("```", "").strip()
        return cleaned if self._is_safe_select(cleaned) else None

    def _summarize_result(self, user_query: str, result_data: List[Dict[str, Any]]) -> str:
        system_prompt = (
            "You summarize analytics results for a scenic digital guide. "
            "Always state that the answer is based on visitor behavior data analysis."
        )
        prompt = (
            f"User question: {user_query}\n"
            f"Analytics result: {json.dumps(result_data, ensure_ascii=False)}\n"
            "Please answer in concise Chinese."
        )
        answer = generate_chat_completion(prompt, system_prompt, temperature=0.2)
        if not answer:
            return "抱歉，我暂时无法生成游客行为分析解读。"
        if not answer.startswith("基于游客行为数据分析"):
            answer = "基于游客行为数据分析，" + answer
        return answer

    def _format_ranked_rows(
        self,
        rows: List[Dict[str, Any]],
        name_key: str,
        value_key: str,
        value_label: str,
        limit: int = 3,
    ) -> Optional[str]:
        if not rows or "error" in rows[0]:
            return None
        parts = []
        for index, row in enumerate(rows[:limit], start=1):
            parts.append(f"{index}. {row[name_key]}（{value_label}{row[value_key]}）")
        return "基于游客行为数据分析，" + "；".join(parts) + "。"

    def _format_single_value(self, rows: List[Dict[str, Any]], key: str, label: str, unit: str = "") -> Optional[str]:
        if not rows or "error" in rows[0]:
            return None
        return f"基于游客行为数据分析，{label}{rows[0][key]}{unit}。"

    def _format_month_rows(self, rows: List[Dict[str, Any]], value_key: str, value_label: str) -> Optional[str]:
        if not rows or "error" in rows[0]:
            return None
        parts = [f"{row['month']}：{row[value_key]}" for row in rows]
        return f"基于游客行为数据分析，{value_label}按月变化为：" + "；".join(parts) + "。"

    def _has_source_conflict(self, query: str) -> bool:
        docx_terms = ("docx", "DOCX", "景区介绍文档", "介绍文档", "景区文档", "资料文档")
        behavior_terms = ("行为数据", "游客消费数据", "游客行为 Excel", "游客行为数据")
        behavior_metric_terms = ("游客", "男性", "女性", "消费", "满意度", "访问量", "平均", "统计", "偏好")
        fact_metric_terms = ("开放时间", "官方开放", "门票价格", "票价", "铜壁板", "佛体", "玄奘", "历史", "文化内涵")
        if any(term in query for term in docx_terms) and any(term in query for term in behavior_metric_terms):
            return True
        if any(term in query for term in behavior_terms) and any(term in query for term in fact_metric_terms):
            return True
        if "当作" in query and any(term in query for term in ("门票", "票价", "开放时间", "文化内涵")):
            return True
        return False

    def _rule_based_response(self, user_query: str) -> Optional[str]:
        query = user_query

        if self._has_source_conflict(query):
            return "抱歉，这个问题要求混用错误的数据源。游客行为数据只能用于统计分析，景区 DOCX 资料只能用于景点事实、历史文化和讲解内容，我不能把一种数据源当作另一种事实依据。"

        if "平均同行人数" in query or "同行人数" in query or "平均团体人数" in query:
            rows = self.execute_sql("select round(avg(cast(group_size as real)), 2) as avg_group_size from tourist_behavior")
            return self._format_single_value(rows, "avg_group_size", "样本游客平均同行人数约为", "人")

        if "一共有多少条" in query or "多少条记录" in query or "总记录" in query:
            rows = self.execute_sql("select count(*) as record_count from tourist_behavior")
            return self._format_single_value(rows, "record_count", "当前游客行为数据共有", "条记录")

        if "女性" in query and ("喜欢" in query or "偏好" in query) and ("类型" in query or "景点" in query):
            rows = self.execute_sql(
                "select attraction_type, count(*) as visits "
                "from tourist_behavior where gender = '女' "
                "group by attraction_type order by visits desc limit 3"
            )
            if rows and "error" not in rows[0]:
                summary = "，".join(f"{row['attraction_type']}（{row['visits']}次）" for row in rows)
                return f"基于游客行为数据分析，女性游客最常选择的景点类型主要是：{summary}。"

        if "男性" in query and ("喜欢" in query or "偏好" in query) and ("类型" in query or "景点" in query):
            rows = self.execute_sql(
                "select attraction_type, count(*) as visits "
                "from tourist_behavior where gender = '男' "
                "group by attraction_type order by visits desc limit 3"
            )
            if rows and "error" not in rows[0]:
                summary = "，".join(f"{row['attraction_type']}（{row['visits']}次）" for row in rows)
                return f"基于游客行为数据分析，男性游客最常选择的景点类型主要是：{summary}。"

        if "女性游客平均总消费" in query:
            rows = self.execute_sql("select round(avg(cast(total_cost as real)), 2) as avg_total_cost from tourist_behavior where gender='女'")
            return self._format_single_value(rows, "avg_total_cost", "女性游客平均总消费约为", "元")

        if "男性游客平均总消费" in query:
            rows = self.execute_sql("select round(avg(cast(total_cost as real)), 2) as avg_total_cost from tourist_behavior where gender='男'")
            return self._format_single_value(rows, "avg_total_cost", "男性游客平均总消费约为", "元")

        if "女性游客平均满意度" in query:
            rows = self.execute_sql("select round(avg(cast(satisfaction as real)), 2) as avg_satisfaction from tourist_behavior where gender='女'")
            return self._format_single_value(rows, "avg_satisfaction", "女性游客平均满意度约为", "分")

        if "男性游客平均满意度" in query:
            rows = self.execute_sql("select round(avg(cast(satisfaction as real)), 2) as avg_satisfaction from tourist_behavior where gender='男'")
            return self._format_single_value(rows, "avg_satisfaction", "男性游客平均满意度约为", "分")

        if "女性游客平均停留" in query:
            rows = self.execute_sql("select round(avg(cast(stay_duration as real)), 2) as avg_stay from tourist_behavior where gender='女'")
            return self._format_single_value(rows, "avg_stay", "女性游客平均停留时长约为", "小时")

        if "男性游客平均停留" in query:
            rows = self.execute_sql("select round(avg(cast(stay_duration as real)), 2) as avg_stay from tourist_behavior where gender='男'")
            return self._format_single_value(rows, "avg_stay", "男性游客平均停留时长约为", "小时")

        if "女性游客访问量最高" in query:
            rows = self.execute_sql(
                "select attraction_name, count(*) as visits from tourist_behavior where gender='女' "
                "group by attraction_name order by visits desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_name", "visits", "访问量")

        if "男性游客访问量最高" in query:
            rows = self.execute_sql(
                "select attraction_name, count(*) as visits from tourist_behavior where gender='男' "
                "group by attraction_name order by visits desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_name", "visits", "访问量")

        if (
            ("平均消费" in query or "人均消费" in query or "总消费" in query or "人均花费" in query or "花费" in query)
            and "餐" not in query
            and not any(keyword in query for keyword in ("最高", "排名", "按月", "上半年", "下半年", "岁", "景点类型", "前3", "女性游客", "男性游客"))
        ):
            rows = self.execute_sql("select round(avg(total_cost), 2) as avg_total_cost from tourist_behavior")
            if rows and "error" not in rows[0]:
                return f"基于游客行为数据分析，样本游客的人均总消费约为{rows[0]['avg_total_cost']}元。"

        if (
            ("餐" in query or "吃饭" in query or "food_cost" in query)
            and "最高" not in query
            and "景点类型" not in query
        ):
            rows = self.execute_sql("select round(avg(food_cost), 2) as avg_food_cost from tourist_behavior")
            if rows and "error" not in rows[0]:
                return f"基于游客行为数据分析，样本游客的人均餐饮消费约为{rows[0]['avg_food_cost']}元。"

        if "停留" in query and "最长" in query and "景点类型" not in query:
            limit = 3 if any(keyword in query for keyword in ("哪几个", "前3", "排名")) else 1
            rows = self.execute_sql(
                "select attraction_name, round(avg(stay_duration), 2) as avg_stay "
                f"from tourist_behavior group by attraction_name order by avg_stay desc limit {limit}"
            )
            return self._format_ranked_rows(rows, "attraction_name", "avg_stay", "平均停留", limit=limit)

        if "满意度" in query and "最高" in query and "景点类型" not in query and "月份" not in query:
            limit = 3 if any(keyword in query for keyword in ("哪几个", "前3", "排名")) else 1
            rows = self.execute_sql(
                "select attraction_name, round(avg(satisfaction), 2) as avg_satisfaction "
                "from tourist_behavior group by attraction_name having count(*) >= 30 "
                f"order by avg_satisfaction desc limit {limit}"
            )
            return self._format_ranked_rows(rows, "attraction_name", "avg_satisfaction", "平均满意度", limit=limit)

        if "平均总消费最高" in query and "景点类型" in query:
            rows = self.execute_sql(
                "select attraction_type, round(avg(cast(total_cost as real)), 2) as avg_total_cost "
                "from tourist_behavior group by attraction_type order by avg_total_cost desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "avg_total_cost", "平均总消费")

        if "平均满意度最高" in query and "景点类型" in query:
            rows = self.execute_sql(
                "select attraction_type, round(avg(cast(satisfaction as real)), 2) as avg_satisfaction "
                "from tourist_behavior group by attraction_type order by avg_satisfaction desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "avg_satisfaction", "平均满意度")

        if "平均满意度最低" in query and "景点类型" in query:
            rows = self.execute_sql(
                "select attraction_type, round(avg(cast(satisfaction as real)), 2) as avg_satisfaction "
                "from tourist_behavior group by attraction_type order by avg_satisfaction asc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "avg_satisfaction", "平均满意度")

        if "平均停留时间最长" in query and "景点类型" in query:
            rows = self.execute_sql(
                "select attraction_type, round(avg(cast(stay_duration as real)), 2) as avg_stay "
                "from tourist_behavior group by attraction_type order by avg_stay desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "avg_stay", "平均停留")

        if "停留时间最短" in query and "景点类型" in query:
            rows = self.execute_sql(
                "select attraction_type, round(avg(cast(stay_duration as real)), 2) as avg_stay "
                "from tourist_behavior group by attraction_type order by avg_stay asc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "avg_stay", "平均停留")

        if "各景点类型的访问量" in query or "景点类型的访问量排名" in query:
            rows = self.execute_sql(
                "select attraction_type, count(*) as visits from tourist_behavior "
                "group by attraction_type order by visits desc limit 8"
            )
            return self._format_ranked_rows(rows, "attraction_type", "visits", "访问量", limit=8)

        if "各景点类型的人均总消费" in query:
            rows = self.execute_sql(
                "select attraction_type, round(avg(cast(total_cost as real)), 2) as avg_total_cost "
                "from tourist_behavior group by attraction_type order by avg_total_cost desc"
            )
            return self._format_ranked_rows(rows, "attraction_type", "avg_total_cost", "人均总消费", limit=8)

        if "各景点类型的平均满意度" in query:
            rows = self.execute_sql(
                "select attraction_type, round(avg(cast(satisfaction as real)), 2) as avg_satisfaction "
                "from tourist_behavior group by attraction_type order by avg_satisfaction desc"
            )
            return self._format_ranked_rows(rows, "attraction_type", "avg_satisfaction", "平均满意度", limit=8)

        if "各景点类型的平均停留" in query:
            rows = self.execute_sql(
                "select attraction_type, round(avg(cast(stay_duration as real)), 2) as avg_stay "
                "from tourist_behavior group by attraction_type order by avg_stay desc"
            )
            return self._format_ranked_rows(rows, "attraction_type", "avg_stay", "平均停留", limit=8)

        if "古镇水乡" in query and ("访问记录" in query or "访问量" in query):
            rows = self.execute_sql("select count(*) as visits from tourist_behavior where attraction_type='古镇水乡'")
            return self._format_single_value(rows, "visits", "古镇水乡类景点访问记录为", "条")

        if "主题乐园类" in query and "平均满意度" in query:
            rows = self.execute_sql("select round(avg(cast(satisfaction as real)), 2) as avg_satisfaction from tourist_behavior where attraction_type='主题乐园'")
            return self._format_single_value(rows, "avg_satisfaction", "主题乐园类景点平均满意度约为", "分")

        if "历史文化类" in query and "平均满意度" in query:
            rows = self.execute_sql("select round(avg(cast(satisfaction as real)), 2) as avg_satisfaction from tourist_behavior where attraction_type='历史文化'")
            return self._format_single_value(rows, "avg_satisfaction", "历史文化类景点平均满意度约为", "分")

        if "风景名胜与休闲度假类" in query and "平均停留" in query:
            rows = self.execute_sql("select round(avg(cast(stay_duration as real)), 2) as avg_stay from tourist_behavior where attraction_type='风景名胜与休闲度假'")
            return self._format_single_value(rows, "avg_stay", "风景名胜与休闲度假类景点平均停留时长约为", "小时")

        if "现代地标类" in query and "平均购物消费" in query:
            rows = self.execute_sql("select round(avg(cast(shopping_cost as real)), 2) as avg_shopping_cost from tourist_behavior where attraction_type='现代地标'")
            return self._format_single_value(rows, "avg_shopping_cost", "现代地标类景点平均购物消费约为", "元")

        if "热门" in query and "类型" in query:
            rows = self.execute_sql(
                "select attraction_type, count(*) as visits "
                "from tourist_behavior group by attraction_type order by visits desc limit 3"
            )
            if rows and "error" not in rows[0]:
                summary = "，".join(f"{row['attraction_type']}（{row['visits']}次）" for row in rows)
                return f"基于游客行为数据分析，当前样本中最热门的景点类型主要是：{summary}。"

        if "消费趋势" in query:
            total = self.execute_sql("select round(avg(total_cost), 2) as avg_total_cost from tourist_behavior")
            top_type = self.execute_sql(
                "select attraction_type, count(*) as visits from tourist_behavior "
                "group by attraction_type order by visits desc limit 1"
            )
            if total and top_type and "error" not in total[0] and "error" not in top_type[0]:
                return (
                    "基于游客行为数据分析，样本游客的人均总消费约为"
                    f"{total[0]['avg_total_cost']}元，当前出现频次最高的景点类型是"
                    f"{top_type[0]['attraction_type']}。这说明游客消费主要集中在高频热门类型景点。"
                )

        if "每个月" in query and ("记录量" in query or "访问量" in query):
            rows = self.execute_sql(
                "select substr(visit_date, 1, 7) as month, count(*) as visits "
                "from tourist_behavior group by month order by month"
            )
            return self._format_month_rows(rows, "visits", "访问量")

        if "平均满意度按月" in query:
            rows = self.execute_sql(
                "select substr(visit_date, 1, 7) as month, round(avg(cast(satisfaction as real)), 2) as avg_satisfaction "
                "from tourist_behavior group by month order by month"
            )
            return self._format_month_rows(rows, "avg_satisfaction", "平均满意度")

        if "平均总消费按月" in query:
            rows = self.execute_sql(
                "select substr(visit_date, 1, 7) as month, round(avg(cast(total_cost as real)), 2) as avg_total_cost "
                "from tourist_behavior group by month order by month"
            )
            return self._format_month_rows(rows, "avg_total_cost", "平均总消费")

        if "访问量最高" in query and "月份" in query:
            rows = self.execute_sql(
                "select substr(visit_date, 1, 7) as month, count(*) as visits "
                "from tourist_behavior group by month order by visits desc limit 1"
            )
            return self._format_ranked_rows(rows, "month", "visits", "访问量", limit=1)

        if "平均消费最高" in query and "月份" in query:
            rows = self.execute_sql(
                "select substr(visit_date, 1, 7) as month, round(avg(cast(total_cost as real)), 2) as avg_total_cost "
                "from tourist_behavior group by month order by avg_total_cost desc limit 1"
            )
            return self._format_ranked_rows(rows, "month", "avg_total_cost", "平均总消费", limit=1)

        if "平均满意度最高" in query and "月份" in query:
            rows = self.execute_sql(
                "select substr(visit_date, 1, 7) as month, round(avg(cast(satisfaction as real)), 2) as avg_satisfaction "
                "from tourist_behavior group by month order by avg_satisfaction desc limit 1"
            )
            return self._format_ranked_rows(rows, "month", "avg_satisfaction", "平均满意度", limit=1)

        if "平均停留时间最高" in query and "月份" in query:
            rows = self.execute_sql(
                "select substr(visit_date, 1, 7) as month, round(avg(cast(stay_duration as real)), 2) as avg_stay "
                "from tourist_behavior group by month order by avg_stay desc limit 1"
            )
            return self._format_ranked_rows(rows, "month", "avg_stay", "平均停留", limit=1)

        if "20到30岁" in query and "偏好" in query:
            rows = self.execute_sql(
                "select attraction_type, count(*) as visits from tourist_behavior where cast(age as real) between 20 and 30 "
                "group by attraction_type order by visits desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "visits", "访问量")

        if "31到45岁" in query and "偏好" in query:
            rows = self.execute_sql(
                "select attraction_type, count(*) as visits from tourist_behavior where cast(age as real) between 31 and 45 "
                "group by attraction_type order by visits desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "visits", "访问量")

        if "46岁以上" in query and "偏好" in query:
            rows = self.execute_sql(
                "select attraction_type, count(*) as visits from tourist_behavior where cast(age as real) >= 46 "
                "group by attraction_type order by visits desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "visits", "访问量")

        if "30岁以下游客平均消费" in query:
            rows = self.execute_sql("select round(avg(cast(total_cost as real)), 2) as avg_total_cost from tourist_behavior where cast(age as real)<30")
            return self._format_single_value(rows, "avg_total_cost", "30岁以下游客平均消费约为", "元")

        if "50岁以上游客平均消费" in query:
            rows = self.execute_sql("select round(avg(cast(total_cost as real)), 2) as avg_total_cost from tourist_behavior where cast(age as real)>50")
            return self._format_single_value(rows, "avg_total_cost", "50岁以上游客平均消费约为", "元")

        if "30岁以下游客平均满意度" in query:
            rows = self.execute_sql("select round(avg(cast(satisfaction as real)), 2) as avg_satisfaction from tourist_behavior where cast(age as real)<30")
            return self._format_single_value(rows, "avg_satisfaction", "30岁以下游客平均满意度约为", "分")

        if "50岁以上游客平均满意度" in query:
            rows = self.execute_sql("select round(avg(cast(satisfaction as real)), 2) as avg_satisfaction from tourist_behavior where cast(age as real)>50")
            return self._format_single_value(rows, "avg_satisfaction", "50岁以上游客平均满意度约为", "分")

        if "消费最高的前3个景点" in query:
            rows = self.execute_sql(
                "select attraction_name, round(avg(cast(total_cost as real)), 2) as avg_total_cost "
                "from tourist_behavior group by attraction_name having count(*) >= 30 order by avg_total_cost desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_name", "avg_total_cost", "平均总消费")

        if "餐饮消费最高的景点类型" in query:
            rows = self.execute_sql(
                "select attraction_type, round(avg(cast(food_cost as real)), 2) as avg_food_cost "
                "from tourist_behavior group by attraction_type order by avg_food_cost desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "avg_food_cost", "平均餐饮消费")

        if "购物消费最高的景点类型" in query:
            rows = self.execute_sql(
                "select attraction_type, round(avg(cast(shopping_cost as real)), 2) as avg_shopping_cost "
                "from tourist_behavior group by attraction_type order by avg_shopping_cost desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "avg_shopping_cost", "平均购物消费")

        if "交通消费最高的景点类型" in query:
            rows = self.execute_sql(
                "select attraction_type, round(avg(cast(transport_cost as real)), 2) as avg_transport_cost "
                "from tourist_behavior group by attraction_type order by avg_transport_cost desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "avg_transport_cost", "平均交通消费")

        if "娱乐消费最高的景点类型" in query:
            rows = self.execute_sql(
                "select attraction_type, round(avg(cast(entertainment_cost as real)), 2) as avg_entertainment_cost "
                "from tourist_behavior group by attraction_type order by avg_entertainment_cost desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "avg_entertainment_cost", "平均娱乐消费")

        if "低满意度记录最多" in query:
            rows = self.execute_sql(
                "select attraction_type, count(*) as low_satisfaction_count from tourist_behavior where cast(satisfaction as real)<3 "
                "group by attraction_type order by low_satisfaction_count desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "low_satisfaction_count", "低满意度记录数")

        if "高满意度记录最多" in query:
            rows = self.execute_sql(
                "select attraction_type, count(*) as high_satisfaction_count from tourist_behavior where cast(satisfaction as real)=5 "
                "group by attraction_type order by high_satisfaction_count desc limit 3"
            )
            return self._format_ranked_rows(rows, "attraction_type", "high_satisfaction_count", "高满意度记录数")

        if "上半年" in query and "平均总消费" in query:
            rows = self.execute_sql(
                "select round(avg(cast(total_cost as real)), 2) as avg_total_cost from tourist_behavior "
                "where visit_date >= '2025-01-01' and visit_date < '2025-07-01'"
            )
            return self._format_single_value(rows, "avg_total_cost", "2025年上半年样本游客平均总消费约为", "元")

        if "下半年" in query and "平均总消费" in query:
            rows = self.execute_sql(
                "select round(avg(cast(total_cost as real)), 2) as avg_total_cost from tourist_behavior "
                "where visit_date >= '2025-07-01' and visit_date < '2026-01-01'"
            )
            return self._format_single_value(rows, "avg_total_cost", "2025年下半年样本游客平均总消费约为", "元")

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
                    "基于游客行为数据分析，女性游客当前最常选择的类型是"
                    f"{female[0]['attraction_type']}，男性游客当前最常选择的类型是"
                    f"{male[0]['attraction_type']}。这说明不同人群在景点偏好上存在明显差异。"
                )

        return None

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


TouristSQLAgent = TouristAnalyticsAgent
