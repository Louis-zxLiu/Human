import os
from pathlib import Path

from app.core.runtime import PROJECT_ROOT


PROJECT_CONDARC = PROJECT_ROOT / ".condarc"
DEFAULT_PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"


def load_env_value(key: str, default: str | None = None) -> str | None:
    value = os.getenv(key)
    if value:
        return value

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as file_obj:
            for raw_line in file_obj:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                env_key, env_value = line.split("=", 1)
                if env_key.strip() == key:
                    stripped = env_value.strip()
                    return stripped if stripped else default
    return default


def get_pip_index_url() -> str:
    return load_env_value("PIP_INDEX_URL", DEFAULT_PIP_INDEX_URL) or DEFAULT_PIP_INDEX_URL


def get_hf_endpoint() -> str:
    return load_env_value("HF_ENDPOINT", DEFAULT_HF_ENDPOINT) or DEFAULT_HF_ENDPOINT


def current_condarc_path() -> Path | None:
    configured = os.getenv("CONDARC")
    if not configured:
        return None
    return Path(configured).resolve()


def using_project_condarc() -> bool:
    current = current_condarc_path()
    return bool(current and current == PROJECT_CONDARC.resolve())
