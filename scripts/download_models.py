import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import whisper
from huggingface_hub import snapshot_download


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "scripts" / "model_manifest.json"


def load_manifest() -> Dict[str, Any]:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def resolve_target_dir(relative_path: str) -> Path:
    return (PROJECT_ROOT / relative_path).resolve()


def has_required_files(target_dir: Path, required_files: List[str]) -> bool:
    return all((target_dir / relative_path).exists() for relative_path in required_files)


def ensure_hf_snapshot(model: Dict[str, Any]) -> Dict[str, Any]:
    target_dir = resolve_target_dir(model["target_dir"])
    target_dir.mkdir(parents=True, exist_ok=True)

    if has_required_files(target_dir, model["required_files"]):
        return {"name": model["name"], "status": "skipped", "reason": "already_ready"}

    snapshot_download(
        repo_id=model["repo_id"],
        local_dir=str(target_dir),
        local_dir_use_symlinks=False,
        resume_download=True,
    )

    if not has_required_files(target_dir, model["required_files"]):
        raise RuntimeError(f"Model downloaded but required files are still missing: {model['name']}")

    return {"name": model["name"], "status": "downloaded", "target_dir": str(target_dir)}


def ensure_openai_whisper(model: Dict[str, Any]) -> Dict[str, Any]:
    target_dir = resolve_target_dir(model["target_dir"])
    target_dir.mkdir(parents=True, exist_ok=True)

    if has_required_files(target_dir, model["required_files"]):
        return {"name": model["name"], "status": "skipped", "reason": "already_ready"}

    whisper.load_model(model["model_name"], download_root=str(target_dir), device="cpu")

    if not has_required_files(target_dir, model["required_files"]):
        raise RuntimeError(f"Whisper runtime download incomplete: {model['name']}")

    return {"name": model["name"], "status": "downloaded", "target_dir": str(target_dir)}


def main() -> int:
    manifest = load_manifest()
    summary: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []

    for model in manifest.get("models", []):
        try:
            if model["type"] == "huggingface_snapshot":
                result = ensure_hf_snapshot(model)
            elif model["type"] == "openai_whisper":
                result = ensure_openai_whisper(model)
            else:
                raise RuntimeError(f"Unsupported model type: {model['type']}")
            summary.append(result)
        except Exception as exc:
            failures.append({"name": model["name"], "error": str(exc)})

    payload = {
        "ok": not failures,
        "downloaded_or_skipped": summary,
        "failures": failures,
        "hint": "If Hugging Face access is unstable, check network access or configure a HF mirror endpoint before retrying."
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
