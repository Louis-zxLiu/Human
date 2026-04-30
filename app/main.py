import os
import sys
import io
from app.core.config import settings, resolve_path

# 强制将标准输出设置为 UTF-8，防止大模型返回 emoji 时在 Windows 终端引发 GBK 编码错误导致崩溃
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 把环境的 Scripts 目录强制加到 PATH 的最前面，确保 whisper 能找到 ffmpeg
env_scripts_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "env", "Scripts"))
if os.path.exists(env_scripts_path):
    os.environ["PATH"] = env_scripts_path + os.pathsep + os.environ.get("PATH", "")

# 【核心修复】将 SoulX-FlashHead 根目录加入到 Python 模块搜索路径中
# 这是因为该模型内部使用了绝对导入 (e.g. `from flash_head.inference import...`)
original_cwd = os.getcwd()
soulx_path = os.path.abspath(os.path.join(original_cwd, "SoulX-FlashHead"))
if soulx_path not in sys.path:
    sys.path.insert(0, soulx_path)

# 尽量在导入 torch 前注入显存分配策略，缓解 Windows + CUDA 的碎片化 OOM
if settings.AVATAR_CUDA_ALLOC_CONF:
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", settings.AVATAR_CUDA_ALLOC_CONF)

from app.core.chroma_telemetry import disable_chroma_telemetry
disable_chroma_telemetry()

# 【核心修复】由于官方 SoulX-FlashHead 仓库在 import 阶段（如 inference.py）
# 就硬编码了相对路径 `open("flash_head/configs/infer_params.yaml")`
# 必须在整个 FastAPI 进程（Uvicorn）导入任何包之前，将进程的 CWD 切换到官方源码目录
original_cwd = os.getcwd()
soulx_path = os.path.abspath(os.path.join(original_cwd, "SoulX-FlashHead"))
if os.path.exists(soulx_path):
    os.chdir(soulx_path)

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.openapi.docs import get_redoc_html
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, chat, interact, kb

# 导入完成后，切回原来的工作目录，防止影响后端其他依赖相对路径的文件（如 RAG 知识库）
os.chdir(original_cwd)

def create_app() -> FastAPI:
    """
    Initialize FastAPI application for the AI Avatar system.
    """
    app = FastAPI(
        title="景区导览服务AI数字人 API",
        description="Phase 3 Core API integrating LLM, RAG, ASR, TTS, Avatar Engine, and Frontend.",
        version="1.0.0",
        redoc_url=None  # Disable default redoc to use custom one
    )

    # CORS Middleware configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files
    # 将存放临时音视频的目录挂载为静态资源目录，以便前端可以访问
    # 这里的绝对路径必须在应用启动前彻底计算好，并且不能受 os.chdir() 的影响
    temp_dir = resolve_path("data/temp")
    
    # 【核心修复】：由于 AvatarEngine 切换了工作目录到 SoulX-FlashHead，
    # 导致后续所有 os.path.join(os.getcwd(), "data", "temp") 都指向了那里！
    # 为了兼容，我们把两个目录都挂载上去，前端访问哪个都不会 404！
    soulx_temp_dir = resolve_path("SoulX-FlashHead/data/temp")
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(soulx_temp_dir, exist_ok=True)
    
    print(f"[System] Mounting static directory for temp files: {soulx_temp_dir}")
    # 优先挂载实际产生文件的那个目录
    app.mount("/static/temp", StaticFiles(directory=soulx_temp_dir), name="static_temp")

    # 将前端 Vue 打包后的目录挂载到 /static 路径下
    frontend_dist = resolve_path("app/static")
    os.makedirs(frontend_dist, exist_ok=True)

    # Include modular routers
    app.include_router(chat.router, tags=["Scenic Chat API"])
    app.include_router(interact.router, prefix="/api", tags=["Multimodal Interaction"])
    app.include_router(kb.router, prefix="/api/v1/kb", tags=["Knowledge Base Management"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin Dashboard"])
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])

    @app.get("/", include_in_schema=False)
    async def root():
        """
        Serve the Vue3 frontend interaction page directly at root.
        """
        static_index_path = resolve_path("app/static/index.html")
        if os.path.exists(static_index_path):
            with open(static_index_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return RedirectResponse(url="/docs")

    @app.get("/login", include_in_schema=False)
    async def login_page():
        """
        Serve the Vue3 Login/Register page.
        """
        static_login_path = resolve_path("app/static/login.html")
        if os.path.exists(static_login_path):
            with open(static_login_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content="Login page not found.", status_code=404)

    @app.get("/admin", include_in_schema=False)
    async def admin_page():
        """
        Serve the Vue3 Admin Dashboard page.
        """
        static_admin_path = resolve_path("app/static/admin.html")
        if os.path.exists(static_admin_path):
            with open(static_admin_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content="Admin page not found.", status_code=404)

    @app.get("/redoc", include_in_schema=False)
    async def redoc_html(req: Request):
        """
        Custom Redoc handler to fix white screen issue caused by CDN accessibility.
        """
        return get_redoc_html(
            openapi_url=app.openapi_url,
            title=app.title + " - ReDoc",
            redoc_js_url="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js",
        )

    @app.get("/health", tags=["System"])
    async def health_check():
        """
        Health check endpoint for microservices.
        """
        return {
            "status": "ok",
            "service": "AI Avatar Backend",
            "environment": "Windows Native",
            "llm_model": settings.LLM_MODEL_NAME
        }

    return app

app = create_app()

if __name__ == "__main__":
    print(f"Starting AI Avatar Server on {settings.HOST}:{settings.PORT}...")
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
