import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
MANIFEST_PATH = PROJECT_ROOT / "scripts" / "model_manifest.json"


def load_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    with open(path, "r", encoding="utf-8") as file_obj:
        for raw_line in file_obj:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def resolve_project_path(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def load_manifest() -> Dict[str, List[Dict[str, object]]]:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def collect_missing_runtime(env_values: Dict[str, str]) -> List[str]:
    missing = []
    if not VENV_PYTHON.exists():
        missing.append("Python virtual environment is missing (.venv).")
    if not ENV_PATH.exists():
        missing.append(".env file is missing.")
    elif env_values.get("LLM_API_KEY") in {"", "sk-placeholder", "your_llm_api_key_here"}:
        missing.append("LLM_API_KEY is missing or still using the placeholder value.")
    return missing


def collect_missing_models(env_values: Dict[str, str]) -> List[str]:
    manifest = load_manifest()
    missing = []
    model_targets = {
        "MODEL_EMBEDDING_PATH": env_values.get("MODEL_EMBEDDING_PATH"),
        "MODEL_AVATAR_PATH": env_values.get("MODEL_AVATAR_PATH"),
        "WHISPER_DOWNLOAD_DIR": env_values.get("WHISPER_DOWNLOAD_DIR"),
    }
    for key, value in model_targets.items():
        if value and not resolve_project_path(value).exists():
            missing.append(f"Configured model path is missing: {key} -> {resolve_project_path(value)}")

    for model in manifest.get("models", []):
        target_dir = resolve_project_path(str(model["target_dir"]))
        required_files = [target_dir / relative_path for relative_path in model.get("required_files", [])]
        if not target_dir.exists() or not all(path.exists() for path in required_files):
            missing.append(f"Model is not ready: {model['name']} -> {target_dir}")
    return missing


def collect_missing_data(env_values: Dict[str, str]) -> List[str]:
    missing = []

    kb_dir = resolve_project_path(env_values.get("KNOWLEDGE_BASE_DIR", "./data/knowledge_base"))
    if not kb_dir.exists():
        missing.append(f"Knowledge base source directory is missing: {kb_dir}")

    chroma_dir = resolve_project_path(env_values.get("CHROMA_DB_DIR", "./data/chroma_db"))
    if not chroma_dir.exists() or not os.listdir(chroma_dir):
        missing.append("Chroma knowledge base is missing. Run build_knowledge_base.bat.")

    behavior_db = PROJECT_ROOT / "data" / "processed" / "tourist_behavior.db"
    if not behavior_db.exists():
        missing.append("Behavior database is missing. Run build_behavior_data.bat.")
        return missing

    conn = sqlite3.connect(str(behavior_db))
    try:
        cursor = conn.cursor()
        for table in ("tourist_behavior", "attractions"):
            exists = cursor.execute(
                "select count(*) from sqlite_master where type='table' and name=?",
                (table,),
            ).fetchone()[0]
            if not exists:
                missing.append(f"Required table is missing in tourist_behavior.db: {table}")
    finally:
        conn.close()

    return missing


def build_next_steps(missing_runtime: List[str], missing_models: List[str], missing_data: List[str]) -> List[str]:
    steps: List[str] = []
    if missing_runtime or missing_models:
        steps.append("Run bootstrap_windows.bat first.")
    if any("LLM_API_KEY" in item or ".env" in item for item in missing_runtime):
        steps.append("Fill the real LLM API configuration in .env.")
    if any("build_behavior_data.bat" in item or "tourist_behavior" in item for item in missing_data):
        steps.append("Run build_behavior_data.bat.")
    if any("build_knowledge_base.bat" in item or "Chroma" in item for item in missing_data):
        steps.append("Run build_knowledge_base.bat.")
    steps.append("edge-tts and the LLM API both require network access at runtime.")
    return steps


def main() -> int:
    env_values = load_env_file(ENV_PATH)
    missing_runtime = collect_missing_runtime(env_values)
    missing_models = collect_missing_models(env_values)
    missing_data = collect_missing_data(env_values)
    problems = missing_runtime + missing_models + missing_data
    next_steps = build_next_steps(missing_runtime, missing_models, missing_data)

    payload = {
        "ok": not problems,
        "problems": problems,
        "missing_runtime": missing_runtime,
        "missing_models": missing_models,
        "missing_data": missing_data,
        "next_steps": next_steps,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
