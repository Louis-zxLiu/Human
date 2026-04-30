import os
import shutil
from fastapi import APIRouter, File, UploadFile, HTTPException
from app.core.config import settings

router = APIRouter()

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    Upload a document to the scenic knowledge base directory.
    This endpoint is only for scenic fact knowledge documents, not for the
    competition behavior-analysis Excel dataset.
    """
    allowed_extensions = [".txt", ".docx", ".xlsx", ".csv"]
    ext = os.path.splitext(file.filename)[1].lower()
    
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {allowed_extensions}")

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    kb_dir = settings.KNOWLEDGE_BASE_DIR
    if not os.path.isabs(kb_dir):
        kb_dir = os.path.join(project_root, kb_dir)

    os.makedirs(kb_dir, exist_ok=True)
    file_path = os.path.join(kb_dir, file.filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Optionally, trigger dynamic RAG db update here.
        # For now, it will be picked up on next startup by init_db.py
        
        return {
            "status": "success",
            "message": f"File {file.filename} uploaded successfully to the scenic knowledge base.",
            "file_path": file_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

@router.get("/list")
async def list_documents():
    """
    List all documents currently in the knowledge base directory.
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    kb_dir = settings.KNOWLEDGE_BASE_DIR
    if not os.path.isabs(kb_dir):
        kb_dir = os.path.join(project_root, kb_dir)

    if not os.path.exists(kb_dir):
        return {"documents": []}
        
    docs = os.listdir(kb_dir)
    return {
        "documents": docs
    }
