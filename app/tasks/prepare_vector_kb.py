import os

from typing import Dict

from app.core.config import resolve_path, settings
from app.core.runtime import merge_runtime_status
from app.rag.init_db import init_knowledge_base


def prepare_vector_kb() -> Dict[str, object]:
    init_knowledge_base()
    chroma_dir = resolve_path(settings.CHROMA_DB_DIR)
    ready = os.path.exists(chroma_dir) and bool(os.listdir(chroma_dir))
    merge_runtime_status({"knowledge_base_ready": ready})
    return {"ok": ready, "chroma_dir": chroma_dir, "message": "Scenic knowledge base prepared."}
