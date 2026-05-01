import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from app.core.mirrors import PROJECT_CONDARC, current_condarc_path, get_hf_endpoint, get_pip_index_url, using_project_condarc
from app.core.runtime_health import collect_runtime_health_report, runtime_failure_messages
from app.core.runtime import CONDA_ENV_PREFIX, FRONTEND_DIST_INDEX, PROJECT_ROOT, conda_available, conda_env_exists, merge_runtime_status


ENV_PATH = PROJECT_ROOT / ".env"
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


def collect_runtime_import_failures() -> List[str]:
    return runtime_failure_messages(collect_runtime_health_report(PROJECT_ROOT))


def collect_missing_runtime(env_values: Dict[str, str]) -> List[str]:
    missing: List[str] = []
    if not conda_available():
        missing.append("Conda is not available on PATH.")
        return missing
    if not PROJECT_CONDARC.exists():
        missing.append(f"Project Conda mirror config is missing: {PROJECT_CONDARC}")
    if not conda_env_exists(CONDA_ENV_PREFIX):
        missing.append(f"Conda environment prefix is missing: {CONDA_ENV_PREFIX}")
    if not ENV_PATH.exists():
        missing.append(".env file is missing.")
    elif env_values.get("LLM_API_KEY") in {"", "sk-placeholder", "your_llm_api_key_here"}:
        missing.append("LLM_API_KEY is missing or still using the placeholder value.")
    missing.extend(collect_runtime_import_failures())
    return missing


def collect_missing_models(env_values: Dict[str, str]) -> List[str]:
    manifest = load_manifest()
    missing: List[str] = []
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
    missing: List[str] = []
    kb_dir = resolve_project_path(env_values.get("KNOWLEDGE_BASE_DIR", "./data/knowledge_base"))
    if not kb_dir.exists():
        missing.append(f"Knowledge base source directory is missing: {kb_dir}")

    chroma_dir = resolve_project_path(env_values.get("CHROMA_DB_DIR", "./data/chroma_db"))
    if not chroma_dir.exists() or not os.listdir(chroma_dir):
        missing.append("Chroma knowledge base is missing. Run prepare-kb.")

    if not FRONTEND_DIST_INDEX.exists():
        missing.append("Frontend build is missing. Run build-frontend.")

    behavior_db = PROJECT_ROOT / "data" / "processed" / "tourist_behavior.db"
    if not behavior_db.exists():
        missing.append("Behavior database is missing. Run prepare-data.")
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


def build_next_steps(
    missing_runtime: List[str],
    missing_models: List[str],
    missing_data: List[str],
    mirror_status: Dict[str, Any],
) -> List[str]:
    steps: List[str] = []
    if missing_runtime or missing_models:
        steps.append("Run bootstrap_windows.bat first.")
    if any("Conda mirror config" in item for item in missing_runtime):
        steps.append("Restore the project-level .condarc file, then rerun bootstrap_windows.bat.")
    if mirror_status["project_condarc_exists"] and not mirror_status["using_project_condarc"]:
        steps.append("Use the provided Windows .bat wrappers or set CONDARC to the project .condarc before running conda commands manually.")
    if any("Runtime import check failed" in item for item in missing_runtime):
        steps.append("Remove D:/Human/env and rerun bootstrap_windows.bat to rebuild the Conda env with clean binary packages.")
    if any("LLM_API_KEY" in item or ".env" in item for item in missing_runtime):
        steps.append("Fill the real LLM API configuration in .env.")
    if any("prepare-data" in item or "tourist_behavior" in item for item in missing_data):
        steps.append(f'Run conda run -p "{CONDA_ENV_PREFIX}" python -m app.cli prepare-data.')
    if any("prepare-kb" in item or "Chroma" in item for item in missing_data):
        steps.append(f'Run conda run -p "{CONDA_ENV_PREFIX}" python -m app.cli prepare-kb.')
    if any("build-frontend" in item or "Frontend build" in item for item in missing_data):
        steps.append(f'Run conda run -p "{CONDA_ENV_PREFIX}" python -m app.cli build-frontend.')
    if missing_runtime or missing_models or missing_data:
        steps.append("edge-tts and the LLM API both require network access at runtime.")
    return steps


def collect_mirror_status() -> Dict[str, Any]:
    condarc_path = current_condarc_path()
    return {
        "project_condarc": str(PROJECT_CONDARC),
        "project_condarc_exists": PROJECT_CONDARC.exists(),
        "current_condarc": str(condarc_path) if condarc_path else None,
        "using_project_condarc": using_project_condarc(),
        "pip_index_url": get_pip_index_url(),
        "hf_endpoint": get_hf_endpoint(),
    }


def collect_doctor_report() -> Dict[str, Any]:
    env_values = load_env_file(ENV_PATH)
    runtime_health = collect_runtime_health_report(PROJECT_ROOT)
    missing_runtime = collect_missing_runtime(env_values)
    missing_models = collect_missing_models(env_values)
    missing_data = collect_missing_data(env_values)
    problems = missing_runtime + missing_models + missing_data
    mirror_status = collect_mirror_status()
    report = {
        "ok": not problems,
        "problems": problems,
        "missing_runtime": missing_runtime,
        "missing_models": missing_models,
        "missing_data": missing_data,
        "runtime_health": runtime_health,
        "mirror_status": mirror_status,
        "next_steps": build_next_steps(missing_runtime, missing_models, missing_data, mirror_status),
    }
    merge_runtime_status(
        {
            "conda_env_ready": not any("Conda environment" in item or "Conda is not available" in item for item in missing_runtime),
            "models_ready": not missing_models,
            "behavior_db_ready": not any("tourist_behavior" in item or "Behavior database" in item for item in missing_data),
            "knowledge_base_ready": not any("Chroma" in item for item in missing_data),
            "frontend_built": not any("Frontend build" in item for item in missing_data),
            "last_doctor": report,
        }
    )
    return report
