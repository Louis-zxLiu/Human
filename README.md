# Human

景区导览服务 AI 数字人项目协作说明。

当前版本已经完成两轮核心整改，运行逻辑按以下三层分工：

- `FACT`：灵山胜境事实知识问答
- `ANALYTICS`：游客行为分析问答
- `RECOMMEND`：个性化路线推荐

同时支持弱 GPS 多轮定位演示、后台分析看板、标准题集回归验证。

## 1. 运行环境

项目当前默认面向 Windows 本地运行，根目录已经提供了完整的批处理脚本：

- `setup_windows.bat`：准备 Python 环境与依赖
- `build_behavior_data.bat`：构建行为分析数据库
- `build_knowledge_base.bat`：构建景区知识库
- `start_windows.bat`：预检并启动系统

## 2. 首次协作运行流程

建议按下面顺序执行，不要跳步：

### 第一步：准备环境

双击或运行：

```bat
setup_windows.bat
```

它会做这些事：

- 检查 `env\python.exe` 是否存在
- 自动用 `.env.example` 生成 `.env`（如果本地还没有）
- 安装 `requirements.txt`
- 安装 `SoulX-FlashHead` 运行依赖

### 第二步：填写 `.env`

重点确认下面几个字段：

```env
LLM_API_KEY=your_llm_api_key_here
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini
MODEL_EMBEDDING_PATH=./models/bge-large-zh-v1.5
MODEL_AVATAR_PATH=./models/SoulX-FlashHead-Lite-1.3B
KNOWLEDGE_BASE_DIR=./data/knowledge_base
CHROMA_DB_DIR=./data/chroma_db
```

说明：

- `LLM_API_KEY` 必须填真实值，否则联网大模型能力不可用
- `edge-tts` 运行时需要联网
- 前端目前仍依赖 CDN 资源

### 第三步：构建行为分析数据库

运行：

```bat
build_behavior_data.bat
```

它会做两件事：

- 把灵山胜境结构化景点资料导入 `attractions`
- 把比赛方 Excel 导入 `tourist_behavior`

注意：

- 比赛方提供的 `data/raw_sql_data/景点景区旅游数据行为分析数据.xlsx` 只用于行为分析
- 它**不是**景区事实知识库

### 第四步：构建景区知识库

运行：

```bat
build_knowledge_base.bat
```

它会把 `data/knowledge_base` 下的灵山资料写入 Chroma 向量库，用于景区讲解与补充检索。

### 第五步：启动系统

运行：

```bat
start_windows.bat
```

启动脚本会先执行预检，再启动后端服务。

如果预检失败，优先检查：

1. `.env` 是否填写完整
2. 模型目录是否存在
3. 行为数据库是否已构建
4. 知识库是否已构建

## 3. 启动成功后访问地址

游客前台：

```text
http://localhost:8000/
```

管理后台：

```text
http://localhost:8000/admin
```

默认管理员账号：

```text
admin / admin123
```

## 4. 推荐的验证方式

### 4.1 运行标准题集

项目已提供第二批标准评测脚本：

```bat
env\python.exe tests\run_eval.py
```

当前题集分为三类：

- `FACT`
- `ANALYTICS`
- `RECOMMEND`

评测文件位置：

- [tests/manual_eval_questions.json](/D:/Human/tests/manual_eval_questions.json)
- [tests/run_eval.py](/D:/Human/tests/run_eval.py)

### 4.2 手工验证建议

建议至少验证下面几个问题：

事实问答：

- 灵山梵宫开放时间是什么？
- 灵山大佛在哪里？
- 九龙灌浴有什么看点？

推荐问答：

- 给我推荐一条适合历史爱好者的路线
- 我喜欢自然风光，怎么逛比较合适

分析问答：

- 女性游客更喜欢什么类型的景点？
- 人均消费大概多少？

弱 GPS 演示：

1. 打开前台 `GPS 信号极弱`
2. 问：`我现在在哪，怎么去梵宫？`
3. 再补一句：`我附近能看到大佛和一片大广场`

## 5. 目录说明

### 核心后端

- `app/api/`
  - 接口层
- `app/rag/`
  - 问答编排、事实代理、分析代理、推荐代理、位置代理
- `app/services/`
  - ASR、TTS、数字人引擎、日志服务

### 数据与模型

- `data/knowledge_base/`
  - 灵山景区文档
- `data/raw_sql_data/`
  - 比赛方行为分析 Excel
- `data/processed/`
  - SQLite 数据库与处理产物
- `models/`
  - 本地模型资源

### 文档与测试

- `docs/`
  - 第二批改造说明、答辩提纲、演示脚本
- `tests/`
  - 标准题集与评测脚本

## 6. 当前版本的关键设计约束

### 数据分层治理

系统明确区分三层数据：

1. 景区知识层  
只回答灵山景区事实问题

2. 游客行为分析层  
只回答偏好、消费、停留、满意度等统计问题

3. 推荐生成层  
结合景区知识与行为分析输出路线推荐

### 弱 GPS 场景

当前弱 GPS 不是“假定位”，而是多轮流程：

1. 识别问路/问位置
2. 追问地标
3. 推测候选位置
4. 输出路线建议

## 7. 常见问题

### Q1：`start_windows.bat` 预检失败

先按顺序重跑：

```text
setup_windows.bat
build_behavior_data.bat
build_knowledge_base.bat
start_windows.bat
```

### Q2：前端能开，但回答失败

优先检查：

- `.env` 中的 `LLM_API_KEY`
- 网络是否可访问 `LLM_API_BASE`
- `edge-tts` 是否可联网

### Q3：后台没数据

说明日志库还没有积累交互记录。先到前台进行几轮问答，再刷新后台。

### Q4：标准题集运行失败

请确认你是在项目根目录执行：

```bat
env\python.exe tests\run_eval.py
```

## 8. 协作者建议工作流

如果你要继续改功能，建议按这个流程：

1. 改代码
2. 跑：

```bat
env\python.exe -m compileall app tests scripts
env\python.exe tests\run_eval.py
```

3. 手工验证前台和后台
4. 再提交变更

## 9. 相关文档

- [总体设计文档.md](/D:/Human/总体设计文档.md)
- [docs/第二批改造说明.md](/D:/Human/docs/第二批改造说明.md)
- [docs/答辩提纲.md](/D:/Human/docs/答辩提纲.md)
- [docs/演示脚本.md](/D:/Human/docs/演示脚本.md)
