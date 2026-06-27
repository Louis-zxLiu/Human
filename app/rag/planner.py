from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from app.core.config import settings
from app.core.scenic_catalog import infer_scenic_slug_from_text
from app.rag.llm_client import generate_chat_completion, llm_is_configured
from app.rag.router_cache import RouterPlanCache


QueryIntent = Literal["FACT", "ANALYTICS", "RECOMMEND", "CHAT"]
ExecutionStrategy = Literal[
    "structured_fact",
    "hybrid_rag",
    "semantic_sql",
    "route_planner",
    "ask_clarification",
    "refuse_realtime",
    "refuse_source_conflict",
    "general_chat",
]


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

ROUTE_REQUEST_TERMS = (
    "推荐",
    "路线",
    "行程",
    "安排",
    "规划",
    "怎么走",
    "咋走",
    "怎么逛",
    "咋逛",
    "怎么游览",
    "如何游览",
    "每站",
    "下一步",
    "核心节点",
    "核心景点",
    "经典首游",
    "带我走",
)

ROUTE_PROFILE_TERMS = {
    "history": ("历史", "文化", "人文", "佛教", "禅意", "古刹", "礼佛", "梵宫"),
    "nature": ("自然", "风光", "湖景", "拍照", "打卡", "花海"),
    "family": ("亲子", "孩子", "儿童", "家庭", "老人", "长辈"),
    "architecture": ("建筑", "艺术", "空间", "坛城", "工艺"),
    "relaxed": ("轻松", "慢游", "慢慢", "休闲", "夜游", "放松", "不赶路"),
}

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
    """Let the dialog agent choose the next action, with only hard safety guards in code."""

    def __init__(self, cache: Optional[RouterPlanCache] = None) -> None:
        self.cache = cache or RouterPlanCache()

    def plan(
        self,
        user_query: str,
        scenic_slug: Optional[str] = None,
        conversation_context: Optional[List[Dict[str, Any]]] = None,
        session_memory: Optional[Dict[str, Any]] = None,
    ) -> QueryPlan:
        llm_plan = self._plan_with_llm(
            user_query,
            scenic_slug=scenic_slug,
            conversation_context=conversation_context,
            session_memory=session_memory,
        )
        if llm_plan:
            return llm_plan
        semantic_fallback = self._semantic_fallback_plan(user_query, scenic_slug=scenic_slug)
        if semantic_fallback:
            semantic_fallback.planner_source = "llm_planner_failed_semantic_fallback" if llm_is_configured() else "heuristic_fallback"
            return semantic_fallback
        if llm_is_configured():
            return QueryPlan(
                intent="CHAT",
                strategy="ask_clarification",
                scenic_slug=scenic_slug or infer_scenic_slug_from_text(user_query),
                question_type="description",
                confidence=0.4,
                reasoning=["LLM planner failed; asking for clarification instead of using heuristic semantic routing."],
                chat_reply="我需要先确认一下你的具体需求：你想查景点资料、规划路线，还是分析游客数据？",
                planner_source="llm_planner_failed",
            )
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

        if self._is_simple_social_chat(query):
            return QueryPlan(
                intent="CHAT",
                strategy="general_chat",
                scenic_slug=resolved_scenic_slug,
                confidence=0.78,
                reasoning=["LLM planner unavailable; handled only simple social chat locally."],
                chat_reply="你好，我在。",
                planner_source="heuristic_fallback",
            )

        semantic_plan = self._semantic_fallback_plan(query, scenic_slug=resolved_scenic_slug)
        if semantic_plan:
            return semantic_plan

        return QueryPlan(
            intent="CHAT",
            strategy="ask_clarification",
            scenic_slug=resolved_scenic_slug,
            question_type="description",
            confidence=0.62,
            reasoning=["LLM planner unavailable; asked for clarification instead of guessing a tool route."],
            chat_reply="我需要先确认一下你的具体需求：你想查景点资料、规划路线，还是分析游客数据？",
            planner_source="heuristic_fallback",
        )

    def _plan_with_llm(
        self,
        user_query: str,
        scenic_slug: Optional[str] = None,
        conversation_context: Optional[List[Dict[str, Any]]] = None,
        session_memory: Optional[Dict[str, Any]] = None,
    ) -> Optional[QueryPlan]:
        query = str(user_query or "").strip()
        if not query:
            return None

        resolved_scenic_slug = scenic_slug or infer_scenic_slug_from_text(query)
        has_context = bool(conversation_context) or bool(session_memory)
        cached = None if has_context else self.cache.get(query, resolved_scenic_slug, settings.LLM_MODEL_NAME)
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

        context_block = self._format_agent_context(conversation_context, session_memory)
        system_prompt = (
            "你是景区主对话 Agent 的决策器。你只决定下一步动作，不直接回答用户问题。"
            "必须输出严格 JSON，不要输出 Markdown。"
        )
        prompt = (
            "请作为主对话 Agent，为用户问题选择唯一下一步动作。"
            "你不回答问题，只决定是否直接闲聊、追问、调用哪类知识工具，或在真实越界时拒答。\n\n"
            "意图定义：\n"
            "- FACT：景区事实、位置、开放信息、文化历史、讲解内容、景点介绍。\n"
            "- ANALYTICS：基于游客行为样本/Excel/SQL 的统计分析，包括记录数、平均、人均、最多、最高、分布、排名、年龄、性别、消费、满意度、停留时长、景点类型。\n"
            "- RECOMMEND：路线规划、怎么逛、下一步去哪、带老人/孩子、偏好主题、从入口开始、GPS 不准时的游览建议。\n"
            "- CHAT：普通对话、寒暄、确认、询问助手身份，或需要先追问才能继续的开放请求。\n\n"
            "策略定义：\n"
            "- structured_fact：可从景点结构化事实表回答的 FACT。\n"
            "- hybrid_rag：需要 DOCX/历史文化资料、景区整体概况、宽泛讲解依据的 FACT。\n"
            "- semantic_sql：游客行为统计分析。\n"
            "- route_planner：路线/推荐/游览安排。\n"
            "- ask_clarification：用户在问景区相关内容，但缺少必要槽位，应该先追问而不是拒答。例如没有说明具体景点、城市/景区、游览偏好、统计口径或时间范围。\n"
            "- refuse_realtime：实时、当前、今天/明天/下周、天气、排队、停车、交通、预测、隐私或外部系统才知道的问题。\n"
            "- refuse_source_conflict：要求用错误数据源回答，例如用游客行为数据证明官方事实、用 DOCX 统计行为数据、把平均消费当官方票价。\n"
            "- general_chat：无需查库的自然闲聊、寒暄、感谢、告别、能力介绍。\n\n"
            "重要规则：\n"
            "1. 先判断用户真正需要的动作，不要把所有非闲聊都硬塞进知识库。缺信息时优先 ask_clarification，不要用“证据不足”拒答。\n"
            "2. 不要依赖固定关键词，按语义判断。即使没有“游客行为数据”字样，只要在问样本统计/平均/排名/分布，也应为 ANALYTICS + semantic_sql。\n"
            "3. 口语问法也要识别，例如“有啥用”是 core_function，“有啥好玩的”是 highlights，“尺寸材质”是 architecture_params。\n"
            "4. 问“灵山胜境概况/规模/文化称号”这类景区级事实时，用 FACT + hybrid_rag，不要要求补充具体景点。\n"
            "5. 问“介绍一下景点”“讲讲这里”“有什么好看的”但没有具体对象或偏好时，用 CHAT + ask_clarification；可以在追问中给出可选方向。\n"
            "6. 如果上下文里已有 last_attraction 或最近对话明确了对象，用户说“它/这里/这个景点/刚才那个”时应沿用该对象，不要重新追问。\n"
            "7. 如果上一轮是 ask_clarification，本轮是在回答追问，应结合 pending_clarification 继续选择工具。\n"
            "8. 边界/拒答策略优先级最高。凡是询问未来预测、实时状态、当前排队/车位/客流/天气/交通、隐私推断、外部景区实时信息，必须 strategy=refuse_realtime，不能用历史均值代替预测。\n"
            "9. 凡是要求用错误数据源回答，必须 strategy=refuse_source_conflict。例如用游客行为数据证明官方开放时间/高度，或用 DOCX 统计游客平均消费。\n"
            "10. general_chat 可以自然一点，不要提知识库、证据不足或拒答；普通寒暄短答，能力/身份介绍可稍完整。\n\n"
            "参考例子：\n"
            "- “总共有多少条记录？” => ANALYTICS + semantic_sql\n"
            "- “哪5个景点去的人最多？” => ANALYTICS + semantic_sql\n"
            "- “女游客票务平均是多少？” => ANALYTICS + semantic_sql\n"
            "- “玩下来一般要小孩几岁？” => ANALYTICS + semantic_sql\n"
            "- “灵山大照壁有啥用？” => FACT + structured_fact + core_function\n"
            "- “灵山胜境概况里重点讲啥？” => FACT + hybrid_rag + description\n"
            "- “吉祥颂演出信息，评委问时该答哪些事实？” => FACT + hybrid_rag + open_info\n"
            "- “九龙灌浴表演，评委问时该答啥？” => FACT + hybrid_rag + description\n"
            "- “祥符禅寺哪里最值得去？” => FACT + structured_fact + highlights\n"
            "- “去百子戏弥勒玩，有什么特别推荐的体验吗？” => FACT + structured_fact + highlights\n"
            "- “介绍一下景点” => CHAT + ask_clarification + description\n"
            "- “这里有什么好看的？” => CHAT + ask_clarification + highlights\n"
            "- “喜欢佛教文化，灵山胜境咋逛？” => RECOMMEND + route_planner + history\n"
            "- “下周游客满意度大概多少？” => ANALYTICS + refuse_realtime，requires_realtime_data=true\n"
            "- “灵山胜境今天实时有多少人？” => FACT + refuse_realtime，requires_realtime_data=true\n"
            "- “灵山大佛几点开门？从行为数据查。” => FACT + refuse_source_conflict，source_conflict=true\n\n"
            "字段要求：\n"
            "{\n"
            '  "intent": "FACT|ANALYTICS|RECOMMEND|CHAT",\n'
            '  "strategy": "structured_fact|hybrid_rag|semantic_sql|route_planner|ask_clarification|refuse_realtime|refuse_source_conflict|general_chat",\n'
            '  "question_type": "location|open_info|architecture_params|highlights|remarks|history|cultural_meaning|core_function|description",\n'
            '  "route_profile": "history|nature|family|architecture|relaxed|general",\n'
            '  "requires_realtime_data": true/false,\n'
            '  "source_conflict": true/false,\n'
            '  "confidence": 0.0-1.0,\n'
            '  "chat_reply": "仅当 general_chat 或 ask_clarification 时填写中文回复。寒暄不超过24字；身份介绍或追问不超过80字；其他为空",\n'
            '  "reasoning": ["一句话说明"]\n'
            "}\n\n"
            f"已知 scenic_slug：{resolved_scenic_slug or 'unknown'}\n"
            f"{context_block}"
            f"用户问题：{query}\n"
            "只输出 JSON。"
        )

        raw = generate_chat_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.0,
            max_tokens=500,
            return_error_text=False,
            json_mode=True,
        )
        payload = self._parse_json(raw)
        if not payload:
            return None
        if not has_context:
            self.cache.set(query, resolved_scenic_slug, settings.LLM_MODEL_NAME, payload)
        return self._plan_from_payload(payload, resolved_scenic_slug=resolved_scenic_slug, user_query=query)

    @staticmethod
    def _format_agent_context(
        conversation_context: Optional[List[Dict[str, Any]]],
        session_memory: Optional[Dict[str, Any]],
    ) -> str:
        lines: List[str] = []
        memory = session_memory or {}
        if memory:
            compact_memory = {
                key: memory.get(key)
                for key in (
                    "last_intent",
                    "last_strategy",
                    "last_response_kind",
                    "last_attraction",
                    "last_scenic_slug",
                    "last_route_label",
                    "preferences",
                    "last_tools",
                    "pending_clarification",
                )
                if memory.get(key)
            }
            if compact_memory:
                lines.append(f"会话记忆：{json.dumps(compact_memory, ensure_ascii=False)}")
        recent = []
        for item in list(conversation_context or [])[-6:]:
            role = str(item.get("role") or "")[:12]
            content = str(item.get("content") or "").strip()
            if not role or not content:
                continue
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            recent.append(
                {
                    "role": role,
                    "content": content[:180],
                    "meta": {
                        key: meta.get(key)
                        for key in ("intent", "response_kind", "matched_attraction", "recommendation_label")
                        if meta.get(key)
                    },
                }
            )
        if recent:
            lines.append(f"最近对话：{json.dumps(recent, ensure_ascii=False)}")
        return "\n".join(lines) + ("\n" if lines else "")

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
            "ask_clarification",
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
        if QueryPlanner._requires_fabrication_refusal(query) or QueryPlanner._requires_external_event_refusal(query):
            strategy = "refuse_realtime"
            requires_realtime_data = True
        elif QueryPlanner._has_source_conflict(query):
            strategy = "refuse_source_conflict"
            source_conflict = True
        elif QueryPlanner._requires_realtime_data(query) and not QueryPlanner._is_historical_analytics_query(query):
            strategy = "refuse_realtime"
            requires_realtime_data = True
        elif source_conflict:
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
            "ask_clarification": "CHAT",
        }
        if strategy in strategy_intent:
            intent = strategy_intent[strategy]

        if QueryPlanner._is_private_or_live_location_query(query):
            strategy = "refuse_realtime"
            intent = "ANALYTICS"
            requires_realtime_data = True
        if strategy in {"general_chat", "ask_clarification"} and QueryPlanner._is_route_request(query):
            strategy = "route_planner"
            intent = "RECOMMEND"
        if strategy == "general_chat" and QueryPlanner._has_hard_boundary_signal(query):
            return None
        if strategy == "ask_clarification" and (
            QueryPlanner._has_source_conflict(query) or QueryPlanner._requires_realtime_data(query)
        ):
            return None
        if strategy == "refuse_realtime" and QueryPlanner._is_historical_analytics_query(query):
            strategy = "semantic_sql"
            intent = "ANALYTICS"
            requires_realtime_data = False
        if strategy in {"refuse_realtime", "refuse_source_conflict"} and intent == "CHAT":
            intent = QueryPlanner._default_intent(query)
        question_type = str(payload.get("question_type") or "description").strip()
        if question_type not in allowed_question_types:
            question_type = "description"
        # Override: "建筑艺术/工艺/规模/材质" terms imply architecture_params
        if question_type not in {"architecture_params"} and any(
            t in query for t in ("建筑艺术", "建筑工艺", "规模参数", "建筑参数", "尺寸材质", "建筑结构")
        ):
            question_type = "architecture_params"

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
    def _has_hard_boundary_signal(query: str) -> bool:
        return any(
            term in query
            for term in (
                "编",
                "推断",
                "手机号",
                "真实姓名",
                "家庭住址",
                "住址",
                "家住",
                "夜场",
                "烟花",
                "实时",
            )
        )

    @staticmethod
    def _requires_fabrication_refusal(query: str) -> bool:
        if not query:
            return False
        asks_to_invent = any(term in query for term in ("编", "编造", "随便写", "没写也行", "没有资料也行"))
        fact_target = any(term in query for term in ("时间", "开放", "夜场", "烟花", "票价", "门票", "排队", "车位"))
        return asks_to_invent and fact_target

    @staticmethod
    def _requires_external_event_refusal(query: str) -> bool:
        if not query:
            return False
        event_signal = any(term in query for term in ("烟花", "烟花秀", "夜场", "夜间活动"))
        schedule_signal = any(term in query for term in ("几点", "时间", "开始", "开放", "安排"))
        return event_signal and schedule_signal

    @staticmethod
    def _is_simple_social_chat(query: str) -> bool:
        normalized = re.sub(r"\s+", "", str(query or "")).lower()
        return bool(
            re.fullmatch(
                r"(你好|您好|嗨|哈喽|hello|hi|早上好|中午好|下午好|晚上好|在吗|在不在|有人吗|谢谢|多谢|感谢你|谢了|再见|拜拜|bye|goodbye|好的|好哦|收到|明白了|嗯嗯|行|ok|okay)[!,.?~]*",
                normalized,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _is_route_request(query: str) -> bool:
        normalized = re.sub(r"\s+", "", str(query or ""))
        if not normalized:
            return False
        return any(term in normalized for term in ROUTE_REQUEST_TERMS)

    @staticmethod
    def _detect_route_profile(query: str) -> str:
        normalized = str(query or "")
        for profile, terms in ROUTE_PROFILE_TERMS.items():
            if any(term in normalized for term in terms):
                return profile
        return "general"

    @staticmethod
    def _semantic_fallback_plan(user_query: str, scenic_slug: Optional[str] = None) -> Optional[QueryPlan]:
        query = str(user_query or "").strip()
        resolved_scenic_slug = scenic_slug or infer_scenic_slug_from_text(query)
        if QueryPlanner._is_route_request(query):
            return QueryPlan(
                intent="RECOMMEND",
                strategy="route_planner",
                scenic_slug=resolved_scenic_slug,
                question_type="description",
                route_profile=QueryPlanner._detect_route_profile(query),
                confidence=0.82,
                reasoning=["Detected an explicit route-planning request with deterministic semantic fallback."],
                planner_source="heuristic_fallback",
            )
        return None

    @staticmethod
    def _requires_realtime_data(query: str) -> bool:
        return contains_realtime_unsupported_signal(query)

    @staticmethod
    def _is_private_or_live_location_query(query: str) -> bool:
        return bool(re.search(r"(?<![A-Za-z0-9])U\d{3,}", query, flags=re.IGNORECASE)) and any(
            term in query for term in ("位置", "在哪", "哪里", "定位", "轨迹")
        )

    @staticmethod
    def _has_source_conflict(query: str) -> bool:
        if QueryPlanner._is_behavior_cost_stat_query(query):
            return False
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
        if any(term in query for term in ("当作", "当成", "说成", "当")) and any(
            term in query for term in ("门票", "票价", "开放时间", "文化内涵")
        ):
            return True
        return False

    @staticmethod
    def _is_behavior_cost_stat_query(query: str) -> bool:
        if not query:
            return False
        has_cost_field = any(term in query for term in ("门票", "票", "餐饮", "吃饭", "购物", "交通", "娱乐", "花费", "消费", "多少钱"))
        has_stat = any(term in query for term in ("平均", "人均", "均值", "一般", "多少"))
        has_official_boundary = any(term in query for term in ("官方", "当作", "等于", "是不是官方"))
        return has_cost_field and has_stat and not has_official_boundary

    @staticmethod
    def _default_intent(query: str) -> QueryIntent:
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
