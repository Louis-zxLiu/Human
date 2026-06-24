import io
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.api import admin, auth, chat, interact, kb, memory3d, scenic
from app.core.chroma_telemetry import disable_chroma_telemetry
from app.core.config import resolve_path, settings
from app.core.runtime import FRONTEND_DIST_ASSETS, FRONTEND_DIST_INDEX, frontend_build_ready


sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

active_scripts_path = os.path.dirname(sys.executable)
if os.path.exists(active_scripts_path):
    os.environ["PATH"] = active_scripts_path + os.pathsep + os.environ.get("PATH", "")

soulx_path = resolve_path("SoulX-FlashHead")
if soulx_path not in sys.path:
    sys.path.insert(0, soulx_path)

if settings.AVATAR_CUDA_ALLOC_CONF:
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", settings.AVATAR_CUDA_ALLOC_CONF)

disable_chroma_telemetry()


def create_frontend_missing_page() -> str:
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>Frontend Build Required</title>
      <style>
        body { font-family: sans-serif; background: #0f172a; color: #f8fafc; display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }
        .card { max-width: 720px; background:#1e293b; padding: 32px; border-radius: 20px; box-shadow: 0 20px 40px rgba(0,0,0,0.3); }
        code { background:#0f172a; padding:2px 6px; border-radius:6px; }
      </style>
    </head>
    <body>
      <div class="card">
        <h1>Frontend build is missing</h1>
        <p>The backend is running, but the React frontend has not been built yet.</p>
        <p>Run <code>python -m app.cli build-frontend</code> and then restart the backend.</p>
      </div>
    </body>
    </html>
    """


def serve_frontend_shell() -> HTMLResponse:
    if not frontend_build_ready():
        return HTMLResponse(content=create_frontend_missing_page(), status_code=503)
    return HTMLResponse(content=FRONTEND_DIST_INDEX.read_text(encoding="utf-8"))


def create_app() -> FastAPI:
    app = FastAPI(
        title="景区导览服务 AI 数字人 API",
        description="Unified engineering backend for scenic Q&A, recommendation, analytics and avatar interaction.",
        version="2.0.0",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    soulx_temp_dir = resolve_path("SoulX-FlashHead/data/temp")
    os.makedirs(soulx_temp_dir, exist_ok=True)
    app.mount("/static/temp", StaticFiles(directory=soulx_temp_dir), name="static_temp")
    scenic_media_dir = resolve_path("app/static/scenic_media")
    os.makedirs(scenic_media_dir, exist_ok=True)
    app.mount("/media", StaticFiles(directory=scenic_media_dir), name="scenic_media")

    if FRONTEND_DIST_ASSETS.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST_ASSETS), name="frontend_assets")

    app.include_router(chat.router, tags=["Scenic Chat API"])
    app.include_router(interact.router, prefix="/api", tags=["Multimodal Interaction"])
    app.include_router(scenic.router, prefix="/api/v1/scenic", tags=["Scenic Product APIs"])
    app.include_router(memory3d.router, prefix="/api/v1/memory3d", tags=["3D Memory"])
    app.include_router(kb.router, prefix="/api/v1/kb", tags=["Knowledge Base Management"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin Dashboard"])
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])

    @app.get("/", include_in_schema=False)
    async def root():
        return serve_frontend_shell()

    @app.get("/login", include_in_schema=False)
    async def login_page():
        return serve_frontend_shell()

    @app.get("/admin", include_in_schema=False)
    async def admin_page():
        return serve_frontend_shell()

    @app.get("/redoc", include_in_schema=False)
    async def redoc_html():
        return get_redoc_html(
            openapi_url=app.openapi_url,
            title=app.title + " - ReDoc",
            redoc_js_url="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js",
        )

    @app.get("/health", tags=["System"])
    async def health_check():
        return {
            "status": "ok",
            "service": "AI Avatar Backend",
            "frontend_built": frontend_build_ready(),
            "llm_model": settings.LLM_MODEL_NAME,
        }

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_routes(full_path: str):
        if full_path.startswith(("api/", "assets/", "media/", "static/", "health", "redoc")):
            return HTMLResponse(content="Not Found", status_code=404)
        return serve_frontend_shell()

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
