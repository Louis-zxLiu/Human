# Human

灵山胜境导览服务 AI 数字人工程版。

当前项目已经收敛为一套可部署、可演示、可评测、可继续迭代的真实工程，覆盖游客前台、管理后台、RAG+SQL 问答、路线推荐、语音交互与数字人联动。

## 当前架构

系统已经从早期的简单业务路由，升级为 planner-first 的 RAG+SQL 架构：

- Planner 先判断问题类型、证据需求、可执行策略和拒答边界。
- 景区结构化事实优先走事实层，不再直接依赖自由检索生成。
- 游客行为分析优先走 semantic SQL，由 LLM 负责意图到查询计划的映射。
- 非结构化景区知识才进入 hybrid RAG，用于历史文化、讲解扩展等深资料场景。
- 路线推荐由独立 route planner 负责，把景区知识、行为偏好与讲解重点合成可执行路线。
- 全链路统一输出响应契约，支持前端展示、日志留痕、评测回放和后续观测。

## 当前能力

- 游客前台
  - React + Vite 单页前端，统一承载登录、对话、语音输入和数字人视频。
  - 支持文本问答、语音问答、路线推荐、弱 GPS 多轮问路。
  - 会话历史按用户隔离保存，历史记录可回看、重命名、删除。
- 管理后台
  - 展示互动量、意图分布、满意度趋势、热点问题、失败样例、知识库状态。
  - 支持数字人音色试听、默认头像上传、画质模式切换。
  - 可以直接查看统一评测结果和知识库构建状态。
- RAG+SQL
  - 景区事实问答：结构化事实优先，必要时补充检索证据。
  - 游客行为分析：semantic SQL 优先，避免把统计问题交给纯生成回答。
  - 深资料问答：hybrid RAG 负责历史文化、讲解资料等长文本场景。
  - 路线推荐：结合景区知识、行为数据与兴趣标签生成推荐路线。
- 语音与数字人
  - Whisper 负责 ASR，Edge-TTS 负责语音合成，SoulX-FlashHead 负责数字人视频。
  - `.webm` 识别链路已固定使用 `imageio-ffmpeg`，不再依赖系统级 `ffmpeg`。

## 响应契约与可观测性

RAG pipeline 现在统一返回以下字段：

- `answer`
- `response_kind`
- `plan`
- `evidence`
- `refusal`
- `warnings`
- `observability`

其中：

- `plan` 记录 planner 的决策、选择的执行策略和关键参数。
- `evidence` 记录事实证据、SQL 摘要、检索片段或路线依据。
- `refusal` 用于机器可读拒答，避免把“不知道”做成不可审计的自然语言。
- `warnings` 记录非致命质量风险，例如证据不足、回退执行、召回偏弱。
- `observability` 记录耗时、回退、trace 等调试信息。

接口层已经同步暴露更丰富的 `rag_metadata`，日志层也已经持久化：

- `plan_json`
- `evidence_json`
- `refusal_json`
- `warnings_json`
- `observability_json`

详细字段定义见 [docs/rag_response_contract.md](/D:/Human/docs/rag_response_contract.md)。

## 项目结构

- `app/api/`
  - 后端 HTTP 接口，包括登录、游客交互、管理后台与高级 RAG 接口。
- `app/rag/`
  - planner、response contract、事实问答、semantic SQL、hybrid RAG、路线推荐与 pipeline。
- `app/services/`
  - ASR、TTS、数字人、日志与运行时服务。
- `app/tasks/`
  - 数据准备、诊断、模型准备和评测任务。
- `frontend/`
  - React + Vite 前端工程。
- `data/knowledge_base/`
  - 景区知识文档。
- `data/raw_sql_data/`
  - 游客行为分析原始 Excel。
- `data/processed/`
  - SQLite 中间结果、头像等处理产物。
- `models/`
  - 本地模型目录。
- `reports/`
  - 统一评测报告与相关输出。

## 环境与依赖

统一依赖入口：

- `environment.yml`

依赖策略：

- Conda 负责 Python、Node.js 与基础二进制依赖。
- `environment.yml` 的 `pip` 部分负责应用层依赖。
- GPU 版 `torch / torchvision / torchaudio` 由启动脚本按 CUDA 轮子安装。
- `openai-whisper` 独立安装，降低构建兼容问题。

关键运行参数来自 `.env`，例如：

```env
AVATAR_DEVICE=cuda
AVATAR_TORCH_DTYPE=float16
AVATAR_WARMUP_SECONDS=0.0
AVATAR_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128
AVATAR_VIDEO_CRF=20
```

## 首次运行

### 1. 准备环境

```bat
bootstrap_windows.bat
```

### 2. 构建数据

```bat
build_behavior_data.bat
build_knowledge_base.bat
```

### 3. 构建前端

```bat
conda run -p "D:/Human/env" python -m app.cli build-frontend
```

### 4. 启动系统

```bat
start_windows.bat
```

启动后访问：

- 游客前台：<http://127.0.0.1:8000/>
- 管理后台：<http://127.0.0.1:8000/admin>
- 登录页：<http://127.0.0.1:8000/login>

默认管理员账号：

```text
admin / admin123
```

## 统一评测

统一评测命令：

```bat
conda run -p "D:/Human/env" python -m app.cli generate-unified-eval --target 1200 --output tests/unified_eval_cases.jsonl
conda run -p "D:/Human/env" python -m app.cli eval-unified --report reports/unified_eval_report.json --markdown-report reports/unified_eval_report.md --strict --fail-under 90
```

最新完整评测结果：

- 总题数：`1200`
- 总分：`99.38 / 100`
- 总失败数：`11`
- 运行时长：`885.966s`

分项结果：

- `docx_structured`: `100.00`
- `docx_rag`: `98.83`
- `behavior_sql`: `99.67`
- `fusion`: `99.36`
- `boundary`: `97.50`

当前剩余长尾问题仅集中在：

- `docx_rag` 的个别术语覆盖
- `behavior_sql` 的个别 top5 尾序表达

报告见：

- [reports/unified_eval_report.json](/D:/Human/reports/unified_eval_report.json)
- [reports/unified_eval_report.md](/D:/Human/reports/unified_eval_report.md)

## 最近这次升级

- 新增 planner-first RAG+SQL 架构。
- 新增统一 response contract。
- 新增 semantic SQL 优先链路。
- 新增机器可读 refusal / warnings / observability。
- API 返回更丰富的 `rag_metadata`。
- 日志持久化新增结构化 JSON 元数据字段。
- 新增响应契约测试与文档。
- 完整统一评测刷新到 `99.38/100`。

## 相关文档

- [总体设计文档.md](/D:/Human/总体设计文档.md)
- [docs/rag_response_contract.md](/D:/Human/docs/rag_response_contract.md)
- [docs/submission/01_部署和使用手册.md](/D:/Human/docs/submission/01_部署和使用手册.md)
- [docs/submission/02_产品总体设计文档.md](/D:/Human/docs/submission/02_产品总体设计文档.md)
- [docs/submission/05_测试评测报告.md](/D:/Human/docs/submission/05_测试评测报告.md)
