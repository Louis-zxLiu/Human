import os
from pydantic_settings import BaseSettings

# 统一解析路径的基准：项目根目录
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def resolve_path(path: str) -> str:
    """将基于项目根目录的相对路径转换为绝对路径，避免被 cwd 污染"""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(PROJECT_ROOT, path))

class Settings(BaseSettings):
    # ==========================================
    # LLM & API Configuration (OpenAI Standard)
    # ==========================================
    LLM_API_KEY: str = "sk-placeholder"
    LLM_API_BASE: str = "https://api.openai.com/v1"
    LLM_MODEL_NAME: str = "gpt-3.5-turbo"
    
    # 注意：在 .env 中，我们定义的是 MODEL_EMBEDDING_NAME 和 MODEL_EMBEDDING_PATH
    MODEL_EMBEDDING_NAME: str = "bge-large-zh-v1.5"
    MODEL_EMBEDDING_PATH: str = "models/bge-large-zh-v1.5"
    # Embedding runtime knobs (avoid GPU VRAM contention with avatar)
    EMBEDDING_DEVICE: str = "cpu"  # cpu|cuda
    EMBEDDING_NORMALIZE: bool = True
    EMBEDDING_QUERY_INSTRUCTION: str = "为这个句子生成表示以用于检索相关文章："

    # ==========================================
    # RAG & Knowledge Base Configuration
    # ==========================================
    CHROMA_DB_DIR: str = "./data/chroma_db"
    KNOWLEDGE_BASE_DIR: str = "./data/knowledge_base"
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50

    # ==========================================
    # Avatar Engine (SoulX-FlashHead Lite 1.3B)
    # ==========================================
    MODEL_AVATAR_NAME: str = "SoulX-FlashHead-Lite-1.3B"
    MODEL_AVATAR_PATH: str = "./models/SoulX-FlashHead-Lite-1.3B"
    AVATAR_DEVICE: str = "cuda"  # cuda|cpu
    AVATAR_TORCH_DTYPE: str = "bfloat16"  # bfloat16|float16|float32
    AVATAR_WARMUP_SECONDS: float = 0.5
    AVATAR_CUDA_ALLOC_CONF: str = "expandable_segments:True,max_split_size_mb:128"
    AVATAR_VIDEO_CRF: int = 20  # Constant Rate Factor (0-51, lower is better quality)
    AVATAR_EMPTY_CACHE_BEFORE_INFER: bool = True
    AVATAR_EMPTY_CACHE_AFTER_INFER: bool = True

    # ==========================================
    # ASR & TTS (Whisper & Edge-TTS)
    # ==========================================
    MODEL_ASR_NAME: str = "Whisper"
    MODEL_ASR_PATH: str = "base"
    WHISPER_DOWNLOAD_DIR: str = "./models/whisper-cache"
    MODEL_TTS_NAME: str = "Edge-TTS"

    # ==========================================
    # Server Configuration
    # ==========================================
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # 对于 Pydantic V2+，推荐使用 model_config 字典或 SettingsConfigDict
    model_config = {
        "env_file": os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }

settings = Settings()
