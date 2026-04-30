# Human

景区导览服务 AI 数字人项目。

当前版本已经完成：

- `FACT`：灵山胜境事实知识问答
- `ANALYTICS`：游客行为分析问答
- `RECOMMEND`：个性化路线推荐
- 弱 GPS 多轮定位演示
- 游客端与后台演示页面

本说明面向**协作者从 GitHub 首次下载项目后，如何跑起完整演示版本**。

## 1. 当前版本的重要事实

### 1.1 TTS 方案

当前项目的 TTS 方案**固定为 `edge-tts`**：

- 不需要下载本地 TTS 模型
- 运行时必须联网
- `.env` 中不需要配置任何本地 TTS 模型目录

### 1.2 模型体积

完整演示模式需要自动下载多个大模型，整体磁盘占用请按 **18GB 到 20GB+** 预留。

### 1.3 平台支持

当前只正式支持：

- Windows

### 1.4 前端依赖

当前前端页面仍依赖 CDN 资源，因此运行时建议保持联网。

## 2. 首次运行推荐顺序

协作者第一次从 GitHub 下载后，固定按下面顺序执行：

1. `bootstrap_windows.bat`
2. 填 `.env`
3. `build_behavior_data.bat`
4. `build_knowledge_base.bat`
5. `start_windows.bat`

不要跳步。

## 3. 第一步：运行 bootstrap

在项目根目录执行：

```bat
bootstrap_windows.bat
```

它会完成以下内容：

- 检查系统 Python
- 创建本地 `.venv`
- 安装 `requirements.txt`
- 安装 `SoulX-FlashHead` 依赖
- 自动生成 `.env`
- 自动下载完整演示模式所需模型

如果你只是看到 `setup_windows.bat`，也可以运行它，但它现在只是 `bootstrap_windows.bat` 的兼容入口。

## 4. 第二步：填写 .env

第一次运行 bootstrap 后，如果根目录还没有 `.env`，脚本会自动从 `.env.example` 生成一份。

协作者至少需要确认：

```env
LLM_API_KEY=your_llm_api_key_here
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini
MODEL_EMBEDDING_PATH=./models/bge-large-zh-v1.5
MODEL_AVATAR_PATH=./models/SoulX-FlashHead-Lite-1.3B
MODEL_ASR_PATH=base
WHISPER_DOWNLOAD_DIR=./models/whisper-cache
MODEL_TTS_NAME=Edge-TTS
```

最重要的是：

- `LLM_API_KEY` 必须改成真实值

## 5. 第三步：构建行为分析数据库

执行：

```bat
build_behavior_data.bat
```

这个步骤会：

- 导入灵山胜境结构化景点事实到 `attractions`
- 导入比赛方行为分析 Excel 到 `tourist_behavior`

注意：

- `data/raw_sql_data/景点景区旅游数据行为分析数据.xlsx` 只用于行为分析
- 它**不是**景区事实知识库

## 6. 第四步：构建景区知识库

执行：

```bat
build_knowledge_base.bat
```

这个步骤会把 `data/knowledge_base/` 下的灵山资料写入 Chroma 向量库，用于景区讲解和补充检索。

## 7. 第五步：启动系统

执行：

```bat
start_windows.bat
```

启动脚本会先跑：

- `scripts/preflight_check.py`

只有预检通过后才会启动服务。

## 8. 启动成功后访问地址

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

## 9. 自动下载的模型

当前完整演示模式默认拉取：

- `BAAI/bge-large-zh-v1.5`
- `Soul-AILab/SoulX-FlashHead-1_3B`
- `facebook/wav2vec2-base-960h`
- Whisper `base` 运行资源

模型清单位置：

- [scripts/model_manifest.json](/D:/Human/scripts/model_manifest.json)

下载脚本位置：

- [scripts/download_models.py](/D:/Human/scripts/download_models.py)

## 10. 推荐的验证方式

### 10.1 标准题集

执行：

```bat
.venv\Scripts\python.exe tests\run_eval.py
```

当前题集按三类组织：

- `FACT`
- `ANALYTICS`
- `RECOMMEND`

相关文件：

- [tests/manual_eval_questions.json](/D:/Human/tests/manual_eval_questions.json)
- [tests/run_eval.py](/D:/Human/tests/run_eval.py)

### 10.2 手工验证建议

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

1. 在前台打开 `GPS 信号极弱`
2. 问：`我现在在哪，怎么去梵宫？`
3. 再补：`我附近能看到大佛和一片大广场`

## 11. 当前目录说明

### 核心后端

- `app/api/`
- `app/rag/`
- `app/services/`

### 数据与模型

- `data/knowledge_base/`
- `data/raw_sql_data/`
- `data/processed/`
- `models/`

### 协作与测试

- `docs/`
- `tests/`
- `scripts/`

## 12. 常见问题

### Q1：bootstrap 失败

优先检查：

- 本机是否有 Python 3.10+
- 网络是否能访问 Hugging Face
- 是否有足够磁盘空间

### Q2：模型下载失败

当前默认从 Hugging Face / 官方源拉取。

请先检查：

- 网络连接
- Hugging Face 是否可访问
- 重试 `bootstrap_windows.bat`

如果未来你们接入 HF 镜像或私有存储，再补充备用下载源。

### Q3：start 预检失败

先看 `scripts/preflight_check.py` 的 JSON 输出，它会明确告诉你：

- 缺 `.venv`
- 缺 `.env`
- 缺模型
- 缺行为数据库
- 缺知识库

通常恢复顺序是：

```text
bootstrap_windows.bat
build_behavior_data.bat
build_knowledge_base.bat
start_windows.bat
```

### Q4：前台能打开，但回答失败

优先检查：

- `.env` 里的 `LLM_API_KEY`
- `LLM_API_BASE` 是否可访问
- 运行时网络是否可供 `edge-tts` 使用

## 13. 协作者建议工作流

如果你要继续开发，建议每次改动后至少跑：

```bat
.venv\Scripts\python.exe -m compileall app tests scripts
.venv\Scripts\python.exe tests\run_eval.py
```

然后再手工验证前台与后台。

## 14. 相关文档

- [docs/协作者快速开始.md](/D:/Human/docs/协作者快速开始.md)
- [docs/第二批改造说明.md](/D:/Human/docs/第二批改造说明.md)
- [docs/答辩提纲.md](/D:/Human/docs/答辩提纲.md)
- [docs/演示脚本.md](/D:/Human/docs/演示脚本.md)
- [总体设计文档.md](/D:/Human/总体设计文档.md)
