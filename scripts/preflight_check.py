import json
import os
import shutil
import sqlite3
import sys
from typing import Dict, List, Tuple


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")


def load_env_file(path: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as file_obj:
        for raw_line in file_obj:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def resolve_project_path(path_value: str) -> str:
    if os.path.isabs(path_value):
        return path_value
    return os.path.normpath(os.path.join(PROJECT_ROOT, path_value))


def check_env(env_values: Dict[str, str]) -> List[str]:
    errors = []
    required = [
        "LLM_API_KEY",
        "LLM_API_BASE",
        "LLM_MODEL_NAME",
        "MODEL_EMBEDDING_PATH",
        "MODEL_AVATAR_PATH",
        "KNOWLEDGE_BASE_DIR",
        "CHROMA_DB_DIR",
    ]
    for key in required:
        if not env_values.get(key):
            errors.append(f"Missing required .env field: {key}")

    if env_values.get("LLM_API_KEY") in {"", "sk-placeholder", "your_api_key_here"}:
        errors.append("LLM_API_KEY is missing or still using a placeholder value")

    return errors


def check_paths(env_values: Dict[str, str]) -> List[str]:
    errors = []
    for key in ("MODEL_EMBEDDING_PATH", "MODEL_AVATAR_PATH", "KNOWLEDGE_BASE_DIR"):
        value = env_values.get(key)
        if value and not os.path.exists(resolve_project_path(value)):
            errors.append(f"Configured path does not exist: {key} -> {resolve_project_path(value)}")

    asr_value = env_values.get("MODEL_ASR_PATH", "")
    known_whisper_aliases = {"tiny", "base", "small", "medium", "large", "turbo"}
    if asr_value and asr_value not in known_whisper_aliases:
        if not os.path.exists(resolve_project_path(asr_value)):
            errors.append(f"Configured ASR path does not exist: MODEL_ASR_PATH -> {resolve_project_path(asr_value)}")

    return errors


def check_ffmpeg() -> List[str]:
    if shutil.which("ffmpeg"):
        return []
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return []
    except Exception:
        pass
    return ["ffmpeg is not available via PATH or imageio_ffmpeg; avatar video generation will fail"]


def check_chroma(env_values: Dict[str, str]) -> List[str]:
    errors = []
    db_dir = env_values.get("CHROMA_DB_DIR")
    if not db_dir:
        return errors
    resolved = resolve_project_path(db_dir)
    if not os.path.exists(resolved) or not os.listdir(resolved):
        errors.append("Chroma knowledge base is missing; run build_knowledge_base.bat first")
    return errors


def check_behavior_db() -> List[str]:
    db_path = os.path.join(PROJECT_ROOT, "data", "processed", "tourist_behavior.db")
    if not os.path.exists(db_path):
        return ["Behavior database is missing; run build_behavior_data.bat first"]

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        for table in ("tourist_behavior", "attractions"):
            exists = cursor.execute(
                "select count(*) from sqlite_master where type='table' and name=?",
                (table,),
            ).fetchone()[0]
            if not exists:
                return [f"Required table is missing in tourist_behavior.db: {table}"]
        return []
    finally:
        conn.close()


def main() -> int:
    problems: List[str] = []
    env_values = load_env_file(ENV_PATH)

    if not os.path.exists(ENV_PATH):
        problems.append(".env file is missing; copy .env.example to .env and fill the values first")
    else:
        problems.extend(check_env(env_values))
        problems.extend(check_paths(env_values))
        problems.extend(check_chroma(env_values))

    problems.extend(check_ffmpeg())
    problems.extend(check_behavior_db())

    payload = {
        "ok": not problems,
        "problems": problems,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
