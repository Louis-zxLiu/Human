import os
import shutil
import threading
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from app.api.auth import get_current_admin
from app.core.config import resolve_path, settings

router = APIRouter()

_rebuild_lock = threading.Lock()
_rebuild_status = {"running": False, "last_result": None}


def _resolve_kb_dir() -> str:
    kb_dir = settings.KNOWLEDGE_BASE_DIR
    if not os.path.isabs(kb_dir):
        kb_dir = resolve_path(kb_dir)
    return kb_dir


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), _=Depends(get_current_admin)):
    allowed_extensions = [".txt", ".docx", ".xlsx", ".csv"]
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {allowed_extensions}")

    kb_dir = _resolve_kb_dir()
    os.makedirs(kb_dir, exist_ok=True)
    file_path = os.path.join(kb_dir, file.filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"status": "success", "message": f"{file.filename} 上传成功。", "file_path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


@router.get("/list")
async def list_documents(_=Depends(get_current_admin)):
    kb_dir = _resolve_kb_dir()
    if not os.path.exists(kb_dir):
        return {"documents": []}
    docs = [
        {"name": f, "size": os.path.getsize(os.path.join(kb_dir, f))}
        for f in sorted(os.listdir(kb_dir))
        if os.path.isfile(os.path.join(kb_dir, f))
    ]
    return {"documents": docs}


@router.delete("/delete/{filename}")
async def delete_document(filename: str, _=Depends(get_current_admin)):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    kb_dir = _resolve_kb_dir()
    file_path = os.path.join(kb_dir, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail=f"{filename} 不存在")
    os.remove(file_path)
    return {"status": "success", "message": f"{filename} 已删除"}


@router.post("/rebuild")
async def rebuild_knowledge_base(_=Depends(get_current_admin)):
    global _rebuild_status
    if _rebuild_status["running"]:
        return {"status": "running", "message": "重建已在进行中，请稍候"}

    def _run():
        global _rebuild_status
        _rebuild_status["running"] = True
        try:
            from app.rag.init_db import init_knowledge_base
            init_knowledge_base()
            _rebuild_status["last_result"] = {"success": True, "message": "知识库重建完成"}
        except Exception as e:
            _rebuild_status["last_result"] = {"success": False, "message": str(e)}
        finally:
            _rebuild_status["running"] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"status": "started", "message": "知识库重建已启动，通常需要 1-3 分钟"}


@router.get("/rebuild/status")
async def rebuild_status(_=Depends(get_current_admin)):
    return {
        "running": _rebuild_status["running"],
        "last_result": _rebuild_status["last_result"],
    }
