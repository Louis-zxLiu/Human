# Human

灵山胜境导览服务 AI 数字人工程版。

当前项目已经收敛成一套可运行、可演示、可继续迭代的完整工程链路，覆盖游客前台、管理后台、知识问答、推荐、语音交互和数字人生成。

## 当前能力

- 游客前台
  - React + Vite 单页前端，统一承载登录、游客对话和后台入口。
  - 进入页面自动开启一轮新会话，旧会话按用户名保存在本地历史中。
  - 历史会话支持查看、重命名、删除，查看历史时输入区和语音按钮自动只读。
  - 数字人展示区与聊天滚动区完全分离，避免消息过长挤压视频舞台。

- 管理后台
  - 深色数据驾驶舱风格，展示互动量、意图分布、推荐标签分布、满意度趋势、热点问题、失败样例和知识库状态。
  - 数字人运行模式支持后台切换：
    - `省显存`：`float16 + warmup 0.0`
    - `高质量`：`bfloat16 + warmup 0.5`
  - 音色试听、音色保存、默认头像上传均可直接操作。

- 问答与推荐
  - 统一使用 `FACT / ANALYTICS / RECOMMEND` 三类业务路由。
  - 景区事实和游客行为分析数据严格分层，不混用数据来源。
  - 推荐标签对外统一显示中文，后台聚合不再暴露英文内部 key。
  - 推荐标签分类采用“固定标签集合 + LLM 归类”，关键词规则仅作为兜底。

- 语音与数字人
  - Whisper 负责 ASR，Edge-TTS 负责语音合成，SoulX-FlashHead 负责数字人视频。
  - 语音识别已修复 `.webm` 解码依赖问题：后端不再依赖系统安装的 `ffmpeg`，而是显式使用 `imageio-ffmpeg` 自带可执行文件。
  - GPU 数字人视频生成链路已稳定：先按 chunk 推理并安全转到 CPU，再统一封装 mp4，避免先前的 CUDA 帧回传错误。

## 项目结构

- `app/api/`
  - 后端 HTTP 接口，包括认证、游客交互和管理后台。
- `app/rag/`
  - 景区事实问答、推荐、行为分析和路由逻辑。
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
  - SQLite 中间结果、默认头像等处理产物。
- `models/`
  - 本地模型目录。

## 环境与依赖

当前依赖入口统一为：

- `environment.yml`

依赖策略：

- Conda 负责 Python、Node.js 和基础二进制依赖。
- `environment.yml` 的 `pip` 部分负责应用层依赖。
- GPU 版 `torch / torchvision / torchaudio` 由启动脚本按 CUDA 轮子单独安装。
- `openai-whisper` 单独安装，避免构建隔离导致的兼容问题。

关键运行参数来自 `.env`，当前与数字人质量相关的主要项包括：

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

脚本会：

- 创建或修复 `D:\Human\env`
- 根据 `environment.yml` 安装主依赖
- 单独安装 GPU 版 PyTorch
- 单独安装 `openai-whisper`
- 下载项目所需模型
- 检查运行时依赖健康状态

### 2. 准备数据

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

启动后可访问：

- 游客前台：<http://127.0.0.1:8000/>
- 管理后台：<http://127.0.0.1:8000/admin>
- 登录页：<http://127.0.0.1:8000/login>

默认管理员账号：

```text
admin / admin123
```

## 统一 CLI

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

## 最近更新

- 前台完成整体重构，改为视频主位布局。
- 本地历史记录改为按用户名隔离保存。
- 后台完成深色驾驶舱重构。
- 数字人画质模式支持后台切换，并写回 `.env`。
- Whisper 语音识别修复 `.webm` 解码依赖问题。
- GPU 数字人视频生成链路修复，恢复 `video_stream_url` 正常产出。
- 登录页和后台文案收口，去掉“新版”“未分类”和英文推荐标签等不成熟展示。

## 常见排查

### 语音识别直接失败

先检查：

- 浏览器麦克风权限是否已放开
- `http://127.0.0.1:8000/api/v1/interact/audio` 是否可达
- `D:\Human\env\Lib\site-packages\imageio_ffmpeg\binaries\` 下的 ffmpeg 是否存在

### 数字人只返回语音不返回视频

先检查：

- `/api/v1/interact/text` 或 `/api/v1/interact/audio` 返回体里的 `video_stream_url`
- `SoulX-FlashHead/data/temp/` 是否生成对应 `*_video.mp4`
- 当前数字人模式是否为 `高质量`，显存是否足够

### 环境损坏

标准恢复路径：

```powershell
Remove-Item -Recurse -Force D:\Human\env
.\bootstrap_windows.bat
```

## 相关文档

- [README.md](/D:/Human/README.md)
- [总体设计文档.md](/D:/Human/总体设计文档.md)
