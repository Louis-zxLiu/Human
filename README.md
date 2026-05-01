# Human

景区导览服务 AI 数字人工程版。

当前版本已经收敛为一套可复现、可协作、可演示的完整工程主链路：

- 统一使用项目内 Conda 前缀环境 `env`
- 主依赖只保留一个正式入口：`environment.yml`
- GPU 版 `torch / torchvision / torchaudio` 自动按 CUDA 版本单独安装
- `openai-whisper` 单独安装，避免构建隔离问题
- 前端为 React + Vite，后端为 FastAPI
- `start_windows.bat` 会单独弹出后端窗口、自动探活并打开浏览器

## 1. 当前工程结构

### 后端

- `app/api/`：接口层
- `app/rag/`：问答编排、知识检索、推荐与定位
- `app/services/`：ASR、TTS、数字人和日志服务
- `app/tasks/`：数据准备、环境诊断、模型准备、评测任务
- `app/cli.py`：统一工程入口

### 前端

- `frontend/`：React + Vite 工程
- 构建产物输出到 `app/static/dist/`

### 数据

- `data/knowledge_base/`：灵山景区知识文档
- `data/raw_sql_data/`：赛事方行为分析 Excel
- `data/processed/`：SQLite 处理结果
- `models/`：模型缓存目录

## 2. 依赖与环境

主项目现在只保留一个正式依赖入口：

- `environment.yml`

依赖策略如下：

- Conda：安装 Python、Node、本地二进制基础包
- `environment.yml` 的 `pip:` 子段：安装主项目应用层依赖
- GPU PyTorch：单独从官方 CUDA wheel 源安装
- Whisper：单独安装，避免构建隔离问题

镜像与下载源：

- Conda：清华源
- pip：清华 PyPI 源
- Hugging Face：`hf-mirror.com`
- GPU PyTorch：`https://download.pytorch.org/whl/cu126`

`.env` 至少建议确认：

```env
LLM_API_KEY=your_real_key
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini
MODEL_TTS_NAME=Edge-TTS
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
HF_ENDPOINT=https://hf-mirror.com
TORCH_WHL_INDEX_URL=https://download.pytorch.org/whl/cu126
OPENAI_WHISPER_REQUIREMENT=openai-whisper==20250625
```

## 3. 首次运行流程

### 1. 准备环境

```bat
bootstrap_windows.bat
```

它会负责：

- 创建、更新，或在损坏时重建 `D:\Human\env`
- 根据 `environment.yml` 安装主项目依赖
- 单独安装 GPU 版 `torch / torchvision / torchaudio`
- 单独安装 `openai-whisper`
- 校验核心运行时依赖是否完整
- 下载主项目模型

### 2. 填写 `.env`

写入真实的 LLM API Key 与 API Base。

### 3. 准备数据

```bat
build_behavior_data.bat
build_knowledge_base.bat
```

### 4. 构建前端

```bat
conda run -p "D:/Human/env" python -m app.cli build-frontend
```

### 5. 启动系统

```bat
start_windows.bat
```

当前启动脚本会：

- 先做环境健康检查
- 单独弹出 `Human Backend` 后端窗口
- 自动轮询 `http://127.0.0.1:8000/health`
- 成功后自动打印访问地址
- 自动打开浏览器首页

访问地址：

- 前台：`http://127.0.0.1:8000/`
- 后台：`http://127.0.0.1:8000/admin`
- 登录：`http://127.0.0.1:8000/login`

默认管理员：

```text
admin / admin123
```

## 4. 统一 CLI

统一入口：

```bat
conda run -p "D:/Human/env" python -m app.cli <command>
```

常用命令：

```bat
conda run -p "D:/Human/env" python -m app.cli bootstrap
conda run -p "D:/Human/env" python -m app.cli doctor
conda run -p "D:/Human/env" python -m app.cli runtime-health
conda run -p "D:/Human/env" python -m app.cli prepare-data
conda run -p "D:/Human/env" python -m app.cli prepare-kb
conda run -p "D:/Human/env" python -m app.cli build-frontend
conda run -p "D:/Human/env" python -m app.cli start
conda run -p "D:/Human/env" python -m app.cli dev
conda run -p "D:/Human/env" python -m app.cli eval
```

## 5. 业务分层

系统统一分为三类问答链路：

1. `FACT`
   只回答灵山景区事实问题。
2. `ANALYTICS`
   只回答游客行为统计与偏好问题。
3. `RECOMMEND`
   结合景区知识和行为分析生成推荐路线。

赛事方提供的行为分析 Excel：

- 只用于分析层
- 不作为景区事实知识库

## 6. 验证方式

### 环境诊断

```bat
conda run -p "D:/Human/env" python -m app.cli doctor
```

### 运行时健康检查

```bat
conda run -p "D:/Human/env" python -m app.cli runtime-health
```

### 代码检查

```bat
conda run -p "D:/Human/env" python -m compileall app
```

### 题集评测

```bat
conda run -p "D:/Human/env" python -m app.cli eval
```

## 7. 常见问题

### `bootstrap_windows.bat` 失败

优先检查：

- `conda` 是否在 PATH 中
- `.condarc` 是否存在
- 清华镜像与 `hf-mirror.com` 是否可达
- 是否有足够磁盘空间

如果 `doctor` 或 `runtime-health` 提示环境损坏，标准恢复路径：

```powershell
Remove-Item -Recurse -Force D:\Human\env
.\bootstrap_windows.bat
```

### `build_knowledge_base.bat` 失败

先跑：

```bat
conda run -p "D:/Human/env" python -m app.cli runtime-health
```

确认 `torch / langchain / chromadb / sentence_transformers / whisper / edge_tts` 都通过。

### 页面能打开但回答失败

优先检查：

- `LLM_API_KEY`
- `LLM_API_BASE`
- 当前网络是否可供 `edge-tts` 和 LLM API 使用

## 8. 主文档

- [README.md](/D:/Human/README.md)
- [总体设计文档.md](/D:/Human/总体设计文档.md)
