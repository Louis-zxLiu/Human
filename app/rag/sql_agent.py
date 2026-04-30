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

    def _rule_based_response(self, user_query: str) -> Optional[str]:
        query = user_query

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

        if ("平均消费" in query or "人均消费" in query or "总消费" in query or "人均花费" in query or "花费" in query) and "餐" not in query:
            rows = self.execute_sql("select round(avg(total_cost), 2) as avg_total_cost from tourist_behavior")
            if rows and "error" not in rows[0]:
                return f"基于游客行为数据分析，样本游客的人均总消费约为{rows[0]['avg_total_cost']}元。"

        if "餐" in query or "吃饭" in query or "food_cost" in query:
            rows = self.execute_sql("select round(avg(food_cost), 2) as avg_food_cost from tourist_behavior")
            if rows and "error" not in rows[0]:
                return f"基于游客行为数据分析，样本游客的人均餐饮消费约为{rows[0]['avg_food_cost']}元。"

        if "停留" in query and "最长" in query:
            rows = self.execute_sql(
                "select attraction_name, round(avg(stay_duration), 2) as avg_stay "
                "from tourist_behavior group by attraction_name order by avg_stay desc limit 1"
            )
            if rows and "error" not in rows[0]:
                row = rows[0]
                return f"基于游客行为数据分析，平均停留时间最长的景点是{row['attraction_name']}，平均停留约{row['avg_stay']}小时。"

        if "满意度" in query and "最高" in query:
            rows = self.execute_sql(
                "select attraction_name, round(avg(satisfaction), 2) as avg_satisfaction "
                "from tourist_behavior group by attraction_name having count(*) >= 30 "
                "order by avg_satisfaction desc limit 1"
            )
            if rows and "error" not in rows[0]:
                row = rows[0]
                return f"基于游客行为数据分析，平均满意度较高的景点是{row['attraction_name']}，平均满意度约{row['avg_satisfaction']}分。"

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
