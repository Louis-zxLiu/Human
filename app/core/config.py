import os

from pydantic_settings import BaseSettings

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENV_FILE_PATH = os.path.join(PROJECT_ROOT, ".env")


def resolve_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(PROJECT_ROOT, path))


class Settings(BaseSettings):
    LLM_API_KEY: str = "sk-placeholder"
    LLM_API_BASE: str = "https://api.openai.com/v1"
    LLM_MODEL_NAME: str = "gpt-3.5-turbo"

    MODEL_EMBEDDING_NAME: str = "bge-large-zh-v1.5"
    MODEL_EMBEDDING_PATH: str = "models/bge-large-zh-v1.5"
    EMBEDDING_DEVICE: str = "cpu"
    EMBEDDING_NORMALIZE: bool = True
    EMBEDDING_QUERY_INSTRUCTION: str = "为这个句子生成表示以用于检索相关文章："

    CHROMA_DB_DIR: str = "./data/chroma_db"
    KNOWLEDGE_BASE_DIR: str = "./data/knowledge_base"
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50

    MODEL_AVATAR_NAME: str = "SoulX-FlashHead-Lite-1.3B"
    MODEL_AVATAR_PATH: str = "./models/SoulX-FlashHead-Lite-1.3B"
    AVATAR_DEVICE: str = "cuda"
    AVATAR_TORCH_DTYPE: str = "bfloat16"
    AVATAR_WARMUP_SECONDS: float = 0.5
    AVATAR_CUDA_ALLOC_CONF: str = "expandable_segments:True,max_split_size_mb:128"
    AVATAR_VIDEO_CRF: int = 20
    AVATAR_EMPTY_CACHE_BEFORE_INFER: bool = True
    AVATAR_EMPTY_CACHE_AFTER_INFER: bool = True
    AVATAR_DEFAULT_IMAGE_PATH: str = "data/processed/default_avatar.jpg"

    MODEL_ASR_NAME: str = "Whisper"
    MODEL_ASR_PATH: str = "base"
    WHISPER_DOWNLOAD_DIR: str = "./models/whisper-cache"
    ASR_LANGUAGE: str = "zh"
    ASR_MIN_AUDIO_SECONDS: float = 0.6
    ASR_MIN_RMS: float = 0.003
    ASR_NO_SPEECH_THRESHOLD: float = 0.6
    ASR_LOGPROB_THRESHOLD: float = -1.0
    MODEL_TTS_NAME: str = "Edge-TTS"

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    model_config = {
        "env_file": ENV_FILE_PATH,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()


def persist_env_overrides(overrides: dict[str, str]) -> None:
    existing_lines: list[str] = []
    if os.path.exists(ENV_FILE_PATH):
        with open(ENV_FILE_PATH, "r", encoding="utf-8") as file_obj:
            existing_lines = file_obj.read().splitlines()

    next_lines: list[str] = []
    updated_keys: set[str] = set()

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            next_lines.append(line)
            continue

        key, _, _ = line.partition("=")
        normalized_key = key.strip()
        if normalized_key in overrides:
            next_lines.append(f"{normalized_key}={overrides[normalized_key]}")
            updated_keys.add(normalized_key)
        else:
            next_lines.append(line)

    for key, value in overrides.items():
        if key not in updated_keys:
            next_lines.append(f"{key}={value}")

    with open(ENV_FILE_PATH, "w", encoding="utf-8") as file_obj:
        file_obj.write("\n".join(next_lines).rstrip() + "\n")
