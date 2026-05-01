import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / ".runtime"
STATUS_PATH = RUNTIME_DIR / "status.json"
FRONTEND_DIST_DIR = PROJECT_ROOT / "app" / "static" / "dist"
FRONTEND_DIST_INDEX = FRONTEND_DIST_DIR / "index.html"
FRONTEND_DIST_ASSETS = FRONTEND_DIST_DIR / "assets"
CONDA_ENV_PREFIX = PROJECT_ROOT / "env"


def ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_runtime_status() -> Dict[str, Any]:
    if not STATUS_PATH.exists():
        return {
            "updated_at": None,
            "conda_env_ready": False,
            "models_ready": False,
            "behavior_db_ready": False,
            "knowledge_base_ready": False,
            "frontend_built": False,
            "last_doctor": None,
            "last_eval": None,
        }
    with open(STATUS_PATH, "r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def write_runtime_status(status: Dict[str, Any]) -> None:
    ensure_runtime_dir()
    status["updated_at"] = utc_timestamp()
    with open(STATUS_PATH, "w", encoding="utf-8") as file_obj:
        json.dump(status, file_obj, ensure_ascii=False, indent=2)


def merge_runtime_status(patch: Dict[str, Any]) -> Dict[str, Any]:
    status = read_runtime_status()
    status.update(patch)
    write_runtime_status(status)
    return status


def frontend_build_ready() -> bool:
    return FRONTEND_DIST_INDEX.exists() and FRONTEND_DIST_ASSETS.exists()


def conda_available() -> bool:
    try:
        result = subprocess.run(["conda", "--version"], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def conda_env_exists(env_prefix: Path = CONDA_ENV_PREFIX) -> bool:
    if not conda_available():
        return False
    try:
        result = subprocess.run(["conda", "env", "list", "--json"], capture_output=True, text=True)
        if result.returncode != 0:
            return False
        payload = json.loads(result.stdout)
        resolved_prefix = env_prefix.resolve()
        return any(Path(path).resolve() == resolved_prefix for path in payload.get("envs", []))
    except Exception:
        return False
