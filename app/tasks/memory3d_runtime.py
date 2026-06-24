from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from app.core.config import resolve_path, settings
from app.core.mirrors import get_pip_index_url
from app.core.runtime import CONDA_ENV_PREFIX, PROJECT_ROOT


ML_SHARP_REPO = "https://github.com/apple/ml-sharp.git"
ML_SHARP_ZIP_URL = "https://codeload.github.com/apple/ml-sharp/zip/refs/heads/main"
SHARP_DEPS = [
    "click",
    "matplotlib",
    "pillow-heif",
    "plyfile",
    "scipy",
    "timm",
    "gsplat==1.5.3",
]


def sharp_executable_candidates() -> list[Path]:
    names = ["sharp.exe", "sharp.cmd", "sharp"]
    candidates: list[Path] = []
    if os.name == "nt":
        scripts_dir = CONDA_ENV_PREFIX
        candidates.extend(scripts_dir / "Scripts" / name for name in names)
        candidates.extend(scripts_dir / name for name in names)
    else:
        candidates.extend(CONDA_ENV_PREFIX / "bin" / name for name in names)
    return candidates


def find_sharp_executable(command: str | None = None) -> Path | None:
    configured = (command or settings.MEMORY3D_SHARP_COMMAND).strip()
    if configured and configured != "sharp":
        configured_path = Path(resolve_path(configured))
        if configured_path.exists():
            return configured_path
        resolved_configured = shutil.which(configured)
        return Path(resolved_configured) if resolved_configured else None

    for candidate in sharp_executable_candidates():
        if candidate.exists():
            return candidate

    resolved = shutil.which(configured or "sharp")
    return Path(resolved) if resolved else None


def verify_sharp_executable(executable: Path | None = None) -> tuple[bool, str]:
    candidate = executable or find_sharp_executable()
    if not candidate:
        return False, "Sharp CLI executable was not found"
    probe = run([str(candidate), "--help"])
    if probe.returncode == 0:
        return True, str(candidate)
    return False, (probe.stderr or probe.stdout).strip() or "Sharp CLI verification failed"


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd or PROJECT_ROOT),
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PIP_INDEX_URL": os.environ.get("PIP_INDEX_URL") or get_pip_index_url(),
        },
    )


def ensure_ml_sharp_source(source_dir: Path) -> dict[str, Any]:
    source_dir.parent.mkdir(parents=True, exist_ok=True)
    if (source_dir / ".git").exists():
        result = run(["git", "pull", "--ff-only"], cwd=source_dir)
        if result.returncode == 0:
            return {"status": "updated", "source_dir": str(source_dir)}
        return {
            "status": "present",
            "source_dir": str(source_dir),
            "warning": (result.stderr or result.stdout).strip(),
        }
    if source_dir.exists() and any(source_dir.iterdir()):
        return {"status": "present", "source_dir": str(source_dir), "warning": "source directory is not empty"}
    result = run(["git", "clone", "--depth", "1", ML_SHARP_REPO, str(source_dir)])
    if result.returncode == 0:
        return {"status": "cloned", "source_dir": str(source_dir)}

    clone_error = (result.stderr or result.stdout).strip() or "git clone failed"
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / "ml-sharp-main.zip"
            urllib.request.urlretrieve(ML_SHARP_ZIP_URL, zip_path)
            with zipfile.ZipFile(zip_path) as zip_file:
                zip_file.extractall(temp_path)
            extracted = temp_path / "ml-sharp-main"
            if not extracted.exists():
                raise RuntimeError("Downloaded archive did not contain ml-sharp-main")
            if source_dir.exists():
                shutil.rmtree(source_dir)
            shutil.copytree(extracted, source_dir)
        return {"status": "downloaded_zip", "source_dir": str(source_dir), "clone_warning": clone_error}
    except Exception as exc:
        raise RuntimeError(f"{clone_error}; zip fallback failed: {exc}") from exc


def install_sharp_dependencies() -> dict[str, Any]:
    result = run([
        sys.executable,
        "-m",
        "pip",
        "install",
        *SHARP_DEPS,
    ])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "Sharp dependency install failed")
    return {"status": "installed", "dependencies": SHARP_DEPS}


def install_sharp_cli(source_dir: Path) -> dict[str, Any]:
    result = run([sys.executable, "-m", "pip", "install", "--no-deps", "-e", str(source_dir)])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "Sharp CLI install failed")

    executable = find_sharp_executable()
    if not executable:
        raise RuntimeError("Sharp CLI installed but executable was not found in the project environment")

    probe = run([str(executable), "--help"])
    if probe.returncode != 0:
        raise RuntimeError((probe.stderr or probe.stdout).strip() or "Sharp CLI verification failed")
    return {"status": "installed", "sharp_command": str(executable)}


def ensure_memory3d_runtime() -> dict[str, Any]:
    if not settings.MEMORY3D_ENABLED:
        return {"ok": True, "skipped": True, "reason": "MEMORY3D_ENABLED=false"}

    source_dir = Path(resolve_path(settings.MEMORY3D_SHARP_SOURCE_DIR))
    existing = find_sharp_executable()
    steps: list[dict[str, Any]] = []

    if existing:
        verified, detail = verify_sharp_executable(existing)
        if verified:
            return {"ok": True, "sharp_command": str(existing), "steps": [{"status": "skipped", "reason": "sharp_cli_ready"}]}
        steps.append({"status": "reinstalling", "reason": detail, "sharp_command": str(existing)})

    try:
        steps.append(ensure_ml_sharp_source(source_dir))
        steps.append(install_sharp_dependencies())
        steps.append(install_sharp_cli(source_dir))
        executable = find_sharp_executable()
        return {"ok": True, "sharp_command": str(executable) if executable else "sharp", "steps": steps}
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "steps": steps,
            "hint": "Check GitHub access for apple/ml-sharp and Python package installation logs, then rerun bootstrap_windows.bat.",
        }
