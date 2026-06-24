import json
import hashlib
import os
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from app.core.mirrors import configure_hf_endpoint, get_hf_endpoint
from app.core.runtime import PROJECT_ROOT, merge_runtime_status

configure_hf_endpoint()


MANIFEST_PATH = PROJECT_ROOT / "scripts" / "model_manifest.json"
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 30
DOWNLOAD_PROGRESS_INTERVAL_SECONDS = 15
DOWNLOAD_STALE_TEMP_SECONDS = 24 * 60 * 60


def load_manifest() -> Dict[str, Any]:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def resolve_target_dir(relative_path: str) -> Path:
    expanded = os.path.expanduser(relative_path)
    path = Path(expanded)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def has_required_files(target_dir: Path, model: Dict[str, Any]) -> bool:
    required_files = model.get("required_files", [])
    required_any_files = model.get("required_any_files", [])
    return all((target_dir / relative_path).exists() for relative_path in required_files) and all(
        any((target_dir / relative_path).exists() for relative_path in alternatives)
        for alternatives in required_any_files
    )


def ensure_hf_snapshot(model: Dict[str, Any]) -> Dict[str, Any]:
    target_dir = resolve_target_dir(model["target_dir"])
    target_dir.mkdir(parents=True, exist_ok=True)
    if has_required_files(target_dir, model):
        return {"name": model["name"], "status": "skipped", "reason": "already_ready"}

    configure_hf_endpoint()
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=model["repo_id"],
        local_dir=str(target_dir),
        local_dir_use_symlinks=False,
        resume_download=True,
    )
    if not has_required_files(target_dir, model):
        raise RuntimeError(f"Model downloaded but required files are still missing: {model['name']}")
    return {"name": model["name"], "status": "downloaded", "target_dir": str(target_dir)}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cleanup_stale_downloads(target_dir: Path, filename: str) -> None:
    now = time.time()
    for temp_path in target_dir.glob(f"{filename}.*.download"):
        try:
            if temp_path.stat().st_mtime < now - DOWNLOAD_STALE_TEMP_SECONDS or temp_path.stat().st_size == 0:
                temp_path.unlink()
        except OSError:
            pass


def restore_verified_download(target_path: Path, expected_sha256: str | None) -> bool:
    if not expected_sha256:
        return False
    for temp_path in sorted(target_path.parent.glob(f"{target_path.name}.*.download"), key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            if temp_path.stat().st_size > 0 and sha256_file(temp_path) == expected_sha256:
                os.replace(temp_path, target_path)
                return True
        except OSError:
            pass
    return False


def copy_existing_alias(target_path: Path, alias_paths: list[Path], expected_sha256: str | None) -> bool:
    for alias_path in alias_paths:
        if alias_path.exists() and (not expected_sha256 or sha256_file(alias_path) == expected_sha256):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(alias_path, target_path)
            return True
    return False


def stream_download(url: str, tmp_path: Path, label: str) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Human-Memory3D-ModelDownloader/1.0",
            "Accept": "application/octet-stream,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, open(tmp_path, "wb") as file_obj:
        total_header = response.headers.get("Content-Length")
        total = int(total_header) if total_header and total_header.isdigit() else 0
        downloaded = 0
        last_report = time.time()
        while True:
            chunk = response.read(DOWNLOAD_CHUNK_SIZE)
            if not chunk:
                break
            file_obj.write(chunk)
            downloaded += len(chunk)
            now = time.time()
            if now - last_report >= DOWNLOAD_PROGRESS_INTERVAL_SECONDS:
                if total:
                    percent = downloaded / total * 100
                    print(f"[MODEL] {label}: {downloaded / 1024 / 1024:.1f}/{total / 1024 / 1024:.1f} MB ({percent:.1f}%)", flush=True)
                else:
                    print(f"[MODEL] {label}: {downloaded / 1024 / 1024:.1f} MB", flush=True)
                last_report = now

    if tmp_path.stat().st_size == 0:
        raise RuntimeError("downloaded file is empty")


def direct_file_urls(model: Dict[str, Any]) -> list[str]:
    repo_id = model.get("repo_id")
    filename = model["filename"]
    urls: list[str] = []
    if repo_id:
        endpoint = get_hf_endpoint().rstrip("/")
        urls.append(f"{endpoint}/{repo_id}/resolve/main/{filename}")
        if endpoint != "https://huggingface.co":
            urls.append(f"https://huggingface.co/{repo_id}/resolve/main/{filename}")
    urls.extend(model.get("fallback_urls", []))
    return urls


def ensure_direct_file(model: Dict[str, Any]) -> Dict[str, Any]:
    target_dir = resolve_target_dir(model["target_dir"])
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / model["filename"]
    alias_paths = [target_dir / relative_path for relative_path in model.get("alias_files", [])]
    expected_sha256 = model.get("sha256")
    cleanup_stale_downloads(target_dir, model["filename"])

    if target_path.exists():
        if not expected_sha256 or sha256_file(target_path) == expected_sha256:
            for alias_path in alias_paths:
                alias_path.parent.mkdir(parents=True, exist_ok=True)
                if not alias_path.exists():
                    shutil.copy2(target_path, alias_path)
            return {"name": model["name"], "status": "skipped", "reason": "already_ready"}
        target_path.unlink()
    elif copy_existing_alias(target_path, alias_paths, expected_sha256):
        for alias_path in alias_paths:
            alias_path.parent.mkdir(parents=True, exist_ok=True)
            if not alias_path.exists():
                shutil.copy2(target_path, alias_path)
        return {"name": model["name"], "status": "skipped", "reason": "restored_from_alias"}
    elif restore_verified_download(target_path, expected_sha256):
        for alias_path in alias_paths:
            alias_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target_path, alias_path)
        return {"name": model["name"], "status": "downloaded", "reason": "restored_from_verified_temp", "target_dir": str(target_dir)}

    failures: list[str] = []
    for url in direct_file_urls(model):
        tmp_path = Path(tempfile.mkstemp(prefix=f"{model['filename']}.", suffix=".download", dir=target_dir)[1])
        try:
            stream_download(url, tmp_path, model["name"])
            if expected_sha256 and sha256_file(tmp_path) != expected_sha256:
                raise RuntimeError("SHA256 mismatch")
            os.replace(tmp_path, target_path)
            for alias_path in alias_paths:
                alias_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target_path, alias_path)
            return {"name": model["name"], "status": "downloaded", "target_dir": str(target_dir)}
        except Exception as exc:
            failures.append(f"{url}: {str(exc).splitlines()[0]}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
    raise RuntimeError("; ".join(failures) or f"Unable to download {model['name']}")


def ensure_openai_whisper(model: Dict[str, Any]) -> Dict[str, Any]:
    target_dir = resolve_target_dir(model["target_dir"])
    target_dir.mkdir(parents=True, exist_ok=True)
    if has_required_files(target_dir, model):
        return {"name": model["name"], "status": "skipped", "reason": "already_ready"}

    import whisper

    whisper.load_model(model["model_name"], download_root=str(target_dir), device="cpu")
    if not has_required_files(target_dir, model):
        raise RuntimeError(f"Whisper runtime download incomplete: {model['name']}")
    return {"name": model["name"], "status": "downloaded", "target_dir": str(target_dir)}


def download_required_models() -> Dict[str, Any]:
    manifest = load_manifest()
    summary: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    hf_endpoint = get_hf_endpoint()

    for model in manifest.get("models", []):
        try:
            if model["type"] == "huggingface_snapshot":
                result = ensure_hf_snapshot(model)
            elif model["type"] == "direct_file":
                result = ensure_direct_file(model)
            elif model["type"] == "openai_whisper":
                result = ensure_openai_whisper(model)
            else:
                raise RuntimeError(f"Unsupported model type: {model['type']}")
            summary.append(result)
        except Exception as exc:
            failures.append({"name": model["name"], "error": str(exc)})

    memory3d_names = {
        model["name"]
        for model in manifest.get("models", [])
        if model.get("name", "").lower().startswith("apple sharp")
    }
    failed_names = {failure["name"] for failure in failures}

    payload = {
        "ok": not failures,
        "hf_endpoint": hf_endpoint,
        "downloaded_or_skipped": summary,
        "failures": failures,
        "hint": "If Hugging Face access is unstable, check network access or update HF_ENDPOINT before retrying.",
    }
    merge_runtime_status({
        "models_ready": not failures,
        "memory3d_models_ready": bool(memory3d_names) and not (memory3d_names & failed_names),
    })
    return payload
