# 产品方案介绍 PPT 大纲

项目名称：灵山胜境导览服务 AI 数字人系统

## Slide 1：封面

- 标题：灵山胜境导览服务 AI 数字人系统
- 副标题：面向真实景区服务场景的 planner-first RAG+SQL 工程
- 补充信息：赛题名称、团队信息、日期

## Slide 2：问题定义

- 景区讲解内容固定，无法支持开放式问答
- 游客行为数据难以转成运营洞察
- 纯生成回答容易混用事实与统计

讲解重点：为什么要做一个“能问答、能推荐、能运营、能评测”的完整系统。

## Slide 3：产品目标

- 游客端：文本问答、语音问答、路线推荐、弱 GPS 问路、数字人讲解
- 管理端：知识库状态、行为分析、失败样例、数字人配置
- 评测端：统一评测、结构化观测、可回放日志

## Slide 4：系统总览

```text
游客前台 / 管理后台
        |
        v
FastAPI + Planner-first RAG+SQL
        |
        v
DOCX 知识库 + SQLite 行为库 + 数字人链路
```

讲解重点：系统不是聊天 Demo，而是完整的服务闭环。

## Slide 5：架构升级

- 从简单业务路由升级为 planner-first 架构
- planner 先做策略选择，再调度具体 agent
- 五类策略：`structured_fact`、`semantic_sql`、`hybrid_rag`、`route_planner`、`refusal`

讲解重点：为什么这比“统一走 RAG”更稳。

## Slide 6：数据分层

- 结构化景区事实层
- semantic SQL 行为分析层
- 非结构化深资料层

讲解重点：数据分层是可信问答的前提。

## Slide 7：事实问答

- 结构化事实优先
- 必要时补充检索片段
- 输出 evidence 与可观测元数据

示例问题：

```text
灵山梵宫为什么被称为佛教艺术的卢浮宫？
```

## Slide 8：行为分析

- semantic SQL 负责统计类问题
- 回答来自 SQL 证据，不靠模型编数字
- 支持 TopN、趋势、均值、分组、条件组合

示例问题：

```text
平均停留时间最长的景点是哪些？
```

## Slide 9：路线推荐

- route planner 输出路线节点、时长、讲解重点和依据
- 综合景区知识、行为偏好和兴趣标签

示例问题：

```text
我喜欢自然风光和拍照打卡，请推荐一条适合拍照的路线。
```

## Slide 10：多模态链路

```text
语音输入 -> Whisper -> planner-first pipeline -> Edge-TTS -> SoulX-FlashHead
```

讲解重点：数字人不是装饰，而是和问答链路真正联动。

## Slide 11：弱 GPS 场景

- 用户描述地标
- 系统多轮澄清
- 输出候选位置与下一步建议

讲解重点：解决景区真实场景下“定位不准但能描述周边”的问题。

## Slide 12：统一响应契约

- `answer`
- `response_kind`
- `plan`
- `evidence`
- `refusal`
- `warnings`
- `observability`

讲解重点：让系统不仅会回答，还能被前端、后台、日志和评测共同消费。

## Slide 13：管理后台

- 互动量
- 意图分布
- 满意度趋势
- 热点问题
- 失败样例
- 知识库状态
- 统一评测结果

## Slide 14：可观测日志

- `plan_json`
- `evidence_json`
- `refusal_json`
- `warnings_json`
- `observability_json`

讲解重点：可回放、可审计、可定位问题。

## Slide 15：测试评测结果

- 总题数：`1200`
- 总分：`99.38 / 100`
- 总失败数：`11`
- `docx_structured`: `100.00`
- `docx_rag`: `98.83`
- `behavior_sql`: `99.67`
- `fusion`: `99.36`
- `boundary`: `97.50`

讲解重点：评测已经不只是“过线”，而是接近满分的工程质量。

## Slide 16：剩余长尾问题

- `docx_rag` 个别术语覆盖
- `behavior_sql` 个别 top5 尾序表达

讲解重点：残余问题清晰可定位，不影响主链路稳定性。

## Slide 17：创新点

- planner-first RAG+SQL
- 结构化事实与统计数据严格隔离
- 统一 response contract
- 机器可读 refusal
- 结构化日志可观测

## Slide 18：总结

- 面向游客：可问、可听、可看、可推荐
- 面向景区：可观测、可分析、可维护
- 面向评测：可验证、可回放、可量化
