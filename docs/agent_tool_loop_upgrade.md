# Scenic Guide Agent Tool Loop Upgrade

## 背景

本轮改动把原来的 planner 分流式 RAG，升级为更接近 Agent 的工具调用架构。目标是避免把所有非闲聊问题都硬路由到某个固定链路，同时让主对话 Agent 能基于上下文、记忆和工具 observation 继续决策。

核心原则：

- 主对话 Agent 负责决定下一步动作，而不是依赖业务关键词硬分流。
- 工具调用必须有标准 schema、标准 observation、可追踪 trace。
- 工具结果要回流给 Agent，再决定继续调工具、追问，还是最终回答。
- 闲聊不能被知识库链路误截断，景区任务也不能被误判成闲聊。
- 边界拒答只保留在硬安全场景：实时/未来信息、隐私定位、错误数据源混用。

## 主要改动

### 1. 标准工具运行时

新增 `app/rag/tool_runner.py`：

- `ToolSpec`：描述工具名、说明、输入 schema。
- `ToolCall`：记录工具名、参数、调用原因和 call id。
- `ToolObservation`：标准化工具结果，包含：
  - `status`
  - `confidence`
  - `answer`
  - `response_kind`
  - `evidence`
  - `refusal`
  - `missing_slots`
  - `suggested_next_tools`
  - `trace`
- `ToolRunner`：把现有能力包装成统一工具：
  - `structured_fact`
  - `hybrid_rag`
  - `behavior_sql`
  - `route_planner`

### 2. Agent observation loop

新增 `app/rag/agent_loop.py`：

- `AgentStep`：描述 Agent 每一步动作。
- `AgentLoopController`：根据 observation 决定下一步：
  - `call_tool`
  - `final_answer`
  - `ask_clarification`

现在执行链路为：

```text
User query
  -> QueryPlanner chooses initial action
  -> ToolRunner executes tool
  -> ToolObservation returns to AgentLoopController
  -> Agent decides next step
  -> final synthesis or another tool call
```

LLM 可用时，AgentLoopController 会让模型基于 observation 选择下一步；不可用时使用确定性 fallback policy。

### 3. Pipeline 改造

`app/rag/pipeline.py` 从直接分支调用 agent，改为：

- planner 只选择第一步动作。
- pipeline 构造第一轮 `ToolCall`。
- 工具返回 `ToolObservation`。
- Agent loop 根据 observation 继续决策。
- 最终由 pipeline 做兼容响应封装。

新增 trace 字段：

```json
{
  "observability": {
    "trace": {
      "tools": {
        "available": ["structured_fact", "hybrid_rag", "behavior_sql", "route_planner"],
        "calls": [],
        "self_corrections": 0,
        "final_tool": "structured_fact"
      },
      "agent_loop": {
        "steps": [],
        "step_count": 0
      },
      "synthesis": {
        "source": "tool_observations",
        "observation_count": 1
      }
    }
  }
}
```

### 4. 会话上下文和短期记忆

`app/api/interact.py` 新增会话记忆：

- `last_user_text`
- `last_assistant_text`
- `last_intent`
- `last_strategy`
- `last_response_kind`
- `last_attraction`
- `last_scenic_slug`
- `last_route_label`
- `preferences`
- `last_tools`
- `pending_clarification`

前端会传最近对话上下文，后端会把 session memory 传给 planner 和 pipeline。这样用户说“它”“这里”“刚才那个景点”时，可以沿用上文对象。

### 5. 闲聊保护

对 `general_chat` 增加二次确认：

- 真正寒暄、感谢、确认、告别可以直接短回复。
- 明显任务型问题即使 planner 误判为闲聊，也会继续进入工具链。
- 避免“景区问题被闲聊截断”的问题。

## API 和前端改动

涉及文件：

- `app/api/interact.py`
- `app/api/chat.py`
- `app/api/advanced_rag_router.py`
- `frontend/src/lib/api.js`
- `frontend/src/pages/VisitorApp.jsx`
- `frontend/src/components/ChatMessage.jsx`

主要变化：

- 前端请求携带 `conversation_context`。
- 后端按 `client_session_id` 维护短期 session memory。
- OpenAI-compatible chat endpoint 也会把最近 messages 传入 pipeline。
- 弱 GPS、文本、语音、WebSocket 路径都接入上下文。

## 测试和评测

新增测试：

- `tests/test_tool_runner_agent_loop.py`

已通过的验证：

```powershell
env\python.exe -m unittest tests.test_tool_runner_agent_loop tests.test_rag_contract tests.test_pipeline_general_chat tests.test_router_cache_and_planner tests.test_fact_configured_overrides
```

结果：

```text
Ran 27 tests
OK
```

前端构建：

```powershell
npm run build
```

结果：通过。仍存在既有大 chunk warning 和运行时图片路径提示。

1200 条统一评测：

```powershell
conda run -p D:\Human\env python -m app.cli eval-unified --dataset tests\unified_eval_cases.jsonl --report reports\unified_eval_agent_full1200.json --markdown-report reports\unified_eval_agent_full1200.md --tier full --no-fail
```

结果：

| 指标 | 结果 |
| --- | ---: |
| 样例数 | 1200 |
| 总分 | 99.2 / 100 |
| 是否通过阈值 | 通过 |
| 失败样例 | 15 |
| 耗时 | 612.499 秒 |

分数据源：

| 数据源 | 数量 | 通过 | 得分 | 通过率 |
| --- | ---: | ---: | ---: | ---: |
| behavior_sql | 420 | 420 | 100.0 | 100.0% |
| boundary | 120 | 120 | 96.67 | 100.0% |
| docx_rag | 180 | 175 | 98.53 | 97.22% |
| docx_structured | 320 | 310 | 99.23 | 96.88% |
| fusion | 160 | 160 | 99.71 | 100.0% |

## 已知后续优化

1. `请用 DOCX 资料说明...` 这类合法 DOCX 事实问答，有 5 条被误判为 source conflict。
2. 九龙灌浴、菩提大道、降魔浮雕、百子戏弥勒等少量结构化问答命中景点但字段偏移。
3. `ToolObservation` 的 `missing_slots` 和 `suggested_next_tools` 目前主要由 ToolRunner 推断，后续可让每个工具原生返回。
4. 长期记忆还未持久化，目前是 session 级内存。
5. 前端还没有展示 Agent 工具调用过程，trace 主要用于调试和后台观测。

## 宣传表述建议

可以表述为：

> 主对话 Agent 会根据用户问题、上下文记忆和工具返回结果，按需调用景区事实、文档检索、游客行为分析和路线规划工具，并在工具结果不足时主动自修正或追问。

不建议把当前实现称为 Skill，除非后续产品中显式引入 Skill 抽象。
