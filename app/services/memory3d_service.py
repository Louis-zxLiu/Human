from __future__ import annotations

import gzip
import json
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
from PIL import Image

from app.core.config import resolve_path, settings
from app.tasks.memory3d_runtime import find_sharp_executable, verify_sharp_executable


SPZ_MAGIC = 1347635022
SPZ_VERSION = 3
SQRT1_2 = 1.0 / math.sqrt(2.0)
QUAT_VALUEMASK = (1 << 9) - 1
TASK_RETENTION_SECONDS = 3600
CLEANUP_INTERVAL_SECONDS = 300
SHARP_CHECKPOINT_FILENAME = "sharp_2572gikvuh.pt"


class Memory3DError(Exception):
    pass


class Memory3DEngineUnavailable(Memory3DError):
    pass


class Memory3DValidationError(Memory3DError):
    pass


@dataclass(frozen=True)
class Memory3DPaths:
    workspace: Path
    inputs: Path
    outputs: Path
    thumbnails: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_for(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def normalize_extensions(value: str | Iterable[str]) -> set[str]:
    items = value.split(",") if isinstance(value, str) else list(value)
    return {
        ext if ext.startswith(".") else f".{ext}"
        for ext in (item.strip().lower() for item in items)
        if ext
    }


def safe_stem(filename: str) -> str:
    stem = Path(filename).stem.strip().lower()
    stem = re.sub(r"[^a-z0-9._-]+", "-", stem)
    stem = stem.strip(".-_")
    return stem or "memory"


def display_name_from_filename(filename: str) -> str:
    return Path(filename).stem.strip() or "memory"


def fallback_display_name(item_id: str) -> str:
    return re.sub(r"-[a-f0-9]{8}$", "", item_id) or item_id


def ensure_child_path(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    if candidate_resolved != root_resolved and root_resolved not in candidate_resolved.parents:
        raise Memory3DValidationError("Invalid file path")
    return candidate_resolved


def build_memory3d_paths(workspace_dir: str | None = None) -> Memory3DPaths:
    workspace = Path(resolve_path(workspace_dir or settings.MEMORY3D_WORKSPACE_DIR))
    paths = Memory3DPaths(
        workspace=workspace,
        inputs=workspace / "inputs",
        outputs=workspace / "outputs",
        thumbnails=workspace / "thumbnails",
    )
    for path in (paths.inputs, paths.outputs, paths.thumbnails):
        path.mkdir(parents=True, exist_ok=True)
    return paths


def generate_thumbnail(input_path: Path, thumbnail_path: Path) -> None:
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(input_path) as image:
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        image.thumbnail((320, 320), Image.LANCZOS)
        image.save(thumbnail_path, "JPEG", quality=82)


def ply_to_spz(ply_path: Path, spz_path: Optional[Path] = None, fractional_bits: int = 11) -> Path:
    try:
        from plyfile import PlyData
    except ImportError as exc:
        raise RuntimeError("plyfile is required for SPZ conversion") from exc

    if spz_path is None:
        spz_path = ply_path.with_suffix(".spz")

    plydata = PlyData.read(str(ply_path))
    vert = plydata["vertex"].data
    n = len(vert)

    sh_degree = 0
    scale_factor = 1 << fractional_bits
    sh_c0 = 0.28209479177387814

    header = struct.pack(
        "<IIIBBBB",
        SPZ_MAGIC,
        SPZ_VERSION,
        n,
        sh_degree,
        fractional_bits,
        0,
        0,
    )

    xyz = np.column_stack([
        vert["x"].astype(np.float64),
        vert["y"].astype(np.float64),
        vert["z"].astype(np.float64),
    ])
    quantized = np.round(xyz * scale_factor).astype(np.int32)
    quantized = np.clip(quantized, -(1 << 23) + 1, (1 << 23) - 1)
    unsigned = quantized.astype(np.uint32) & 0xFFFFFF
    b0 = (unsigned & 0xFF).astype(np.uint8)
    b1 = ((unsigned >> 8) & 0xFF).astype(np.uint8)
    b2 = ((unsigned >> 16) & 0xFF).astype(np.uint8)
    centers = np.column_stack([
        b0[:, 0], b1[:, 0], b2[:, 0],
        b0[:, 1], b1[:, 1], b2[:, 1],
        b0[:, 2], b1[:, 2], b2[:, 2],
    ]).flatten().tobytes()

    logits = vert["opacity"].astype(np.float64)
    alphas = 1.0 / (1.0 + np.exp(-np.clip(logits, -20, 20)))
    alpha_bytes = np.round(alphas * 255).clip(0, 255).astype(np.uint8).tobytes()

    colors = np.column_stack([
        0.5 + sh_c0 * vert["f_dc_0"].astype(np.float64),
        0.5 + sh_c0 * vert["f_dc_1"].astype(np.float64),
        0.5 + sh_c0 * vert["f_dc_2"].astype(np.float64),
    ])
    rgb_scale = sh_c0 / 0.15
    rgb_encoded = np.round(((colors - 0.5) / rgb_scale + 0.5) * 255).clip(0, 255).astype(np.uint8)
    rgb_bytes = rgb_encoded.flatten().tobytes()

    log_scales = np.column_stack([
        vert["scale_0"].astype(np.float64),
        vert["scale_1"].astype(np.float64),
        vert["scale_2"].astype(np.float64),
    ])
    scale_encoded = np.round((log_scales + 10.0) * 16.0).clip(0, 255).astype(np.uint8)
    scale_bytes = scale_encoded.flatten().tobytes()

    quats = np.column_stack([
        vert["rot_1"].astype(np.float64),
        vert["rot_2"].astype(np.float64),
        vert["rot_3"].astype(np.float64),
        vert["rot_0"].astype(np.float64),
    ])
    norms = np.linalg.norm(quats, axis=1, keepdims=True)
    norms[norms < 1e-10] = 1.0
    quats /= norms

    quat_packed = np.zeros(n, dtype=np.uint32)
    for index in range(n):
        quat = quats[index]
        largest = int(np.argmax(np.abs(quat)))
        negate = 1 if quat[largest] < 0 else 0
        packed = largest
        for component_index in range(4):
            if component_index == largest:
                continue
            negbit = (1 if quat[component_index] < 0 else 0) ^ negate
            magnitude = int(QUAT_VALUEMASK * (abs(quat[component_index]) / SQRT1_2) + 0.5)
            magnitude = min(QUAT_VALUEMASK, magnitude)
            packed = (packed << 10) | (negbit << 9) | magnitude
        quat_packed[index] = packed & 0xFFFFFFFF
    quat_bytes = quat_packed.astype("<u4").tobytes()

    spz_path.write_bytes(gzip.compress(header + centers + alpha_bytes + rgb_bytes + scale_bytes + quat_bytes, compresslevel=6))
    return spz_path


class Memory3DService:
    def __init__(
        self,
        *,
        paths: Memory3DPaths | None = None,
        enabled: bool | None = None,
        sharp_command: str | None = None,
        device: str | None = None,
        allowed_extensions: set[str] | None = None,
        max_image_mb: int | None = None,
        model_dir: str | Path | None = None,
        start_worker: bool = True,
    ) -> None:
        self.paths = paths or build_memory3d_paths()
        self.enabled = settings.MEMORY3D_ENABLED if enabled is None else enabled
        self.sharp_command = sharp_command or settings.MEMORY3D_SHARP_COMMAND
        self.device = device or settings.MEMORY3D_DEVICE
        self.allowed_extensions = allowed_extensions or normalize_extensions(settings.MEMORY3D_ALLOWED_EXTENSIONS)
        self.max_image_bytes = (max_image_mb if max_image_mb is not None else settings.MEMORY3D_MAX_IMAGE_MB) * 1024 * 1024
        self.model_dir = Path(resolve_path(str(model_dir or settings.MEMORY3D_MODEL_DIR)))
        self.resolved_sharp_command: Path | None = None
        self.task_queue: queue.Queue[str | None] = queue.Queue()
        self.tasks: dict[str, dict[str, Any]] = {}
        self.running_processes: dict[str, subprocess.Popen[str]] = {}
        self.lock = threading.Lock()
        self.metadata_path = self.paths.workspace / "metadata.json"
        self._started = False
        if start_worker:
            self.start()

    def checkpoint_path(self) -> Path:
        return self.model_dir / SHARP_CHECKPOINT_FILENAME

    def status(self) -> dict[str, Any]:
        ready, message = self.engine_ready()
        return {
            "enabled": self.enabled,
            "engine_ready": ready,
            "model_ready": self.checkpoint_path().exists(),
            "message": message,
            "workspace": str(self.paths.workspace),
            "model_dir": str(self.model_dir),
            "allowed_extensions": sorted(self.allowed_extensions),
            "max_image_mb": self.max_image_bytes // 1024 // 1024,
        }

    def engine_ready(self) -> tuple[bool, str]:
        if not self.enabled:
            return False, "3D 记忆功能未启用。"
        if not self.sharp_command:
            return False, "未配置 Sharp CLI 命令。"
        resolved = find_sharp_executable(self.sharp_command)
        if resolved:
            verified, detail = verify_sharp_executable(resolved)
            if not verified:
                return False, f"Sharp CLI 未正确安装：{detail}。请重新运行 bootstrap_windows.bat 或 python -m app.cli memory3d-runtime。"
            self.resolved_sharp_command = resolved
            checkpoint = self.checkpoint_path()
            if not checkpoint.exists():
                return (
                    False,
                    f"Sharp CLI 已就绪，但缺少模型文件 {checkpoint}。请重新运行 bootstrap_windows.bat 或 python -m app.cli _download-models。",
                )
            return True, "Sharp 生成引擎和模型已就绪。"
        return False, f"未找到 Sharp CLI：{self.sharp_command}。请重新运行 bootstrap_windows.bat 以自动安装 Apple ML-Sharp/Sharp CLI，或配置 MEMORY3D_SHARP_COMMAND。"

    def assert_engine_ready(self) -> None:
        ready, message = self.engine_ready()
        if not ready:
            raise Memory3DEngineUnavailable(message)

    def validate_upload(self, filename: str, content: bytes) -> str:
        ext = Path(filename).suffix.lower()
        if ext not in self.allowed_extensions:
            raise Memory3DValidationError(f"Unsupported image type: {ext or 'unknown'}")
        if not content:
            raise Memory3DValidationError("Uploaded file is empty")
        if len(content) > self.max_image_bytes:
            raise Memory3DValidationError("Uploaded image is too large")
        return ext

    def enqueue_upload(self, filename: str, content: bytes) -> dict[str, Any]:
        self.assert_engine_ready()
        ext = self.validate_upload(filename, content)
        item_id = f"{safe_stem(filename)}-{uuid.uuid4().hex[:8]}"
        stored_filename = f"{item_id}{ext}"
        input_path = ensure_child_path(self.paths.inputs, self.paths.inputs / stored_filename)
        input_path.write_bytes(content)

        try:
            generate_thumbnail(input_path, self.paths.thumbnails / f"{item_id}.jpg")
        except Exception as exc:
            print(f"[Memory3D] Thumbnail generation failed for {stored_filename}: {exc}")
        self.set_model_name(item_id, display_name_from_filename(filename))

        task = {
            "id": str(uuid.uuid4()),
            "item_id": item_id,
            "filename": stored_filename,
            "original_filename": filename,
            "name": display_name_from_filename(filename),
            "status": "pending",
            "progress": 0,
            "stage": "queued",
            "created_at": time.time(),
            "updated_at": utc_now(),
            "error": None,
        }
        with self.lock:
            self.tasks[task["id"]] = task
        self.task_queue.put(task["id"])
        return dict(task)

    def list_tasks(self) -> tuple[list[dict[str, Any]], bool]:
        cutoff = time.time() - TASK_RETENTION_SECONDS
        with self.lock:
            stale = [
                task_id
                for task_id, task in self.tasks.items()
                if task["created_at"] < cutoff and task["status"] in {"completed", "failed", "cancelled"}
            ]
            for task_id in stale:
                self.tasks.pop(task_id, None)
            tasks = [dict(task) for task in self.tasks.values()]
        tasks.sort(key=lambda item: item["created_at"], reverse=True)
        return tasks, any(task["status"] in {"pending", "processing"} for task in tasks)

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                raise KeyError(task_id)
            if task["status"] == "pending":
                task["status"] = "cancelled"
                task["stage"] = "cancelled"
                task["updated_at"] = utc_now()
                return {"success": True, "message": "Task cancelled"}
            if task["status"] == "processing":
                task["status"] = "cancelled"
                task["stage"] = "cancelled"
                task["updated_at"] = utc_now()
                process = self.running_processes.get(task_id)
                if process:
                    process.terminate()
                return {"success": True, "message": "Task cancellation requested"}
            raise ValueError(f"Task already {task['status']}")

    def gallery(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for ply_path in self.paths.outputs.glob("*.ply"):
            item = self.gallery_item(ply_path.stem)
            if item:
                items.append(item)
        items.sort(key=lambda item: item["updated_at"], reverse=True)
        return items

    def read_metadata(self) -> dict[str, Any]:
        if not self.metadata_path.exists():
            return {}
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def write_metadata(self, metadata: dict[str, Any]) -> None:
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def model_metadata(self, item_id: str) -> dict[str, Any]:
        metadata = self.read_metadata().get(item_id)
        return metadata if isinstance(metadata, dict) else {}

    def set_model_name(self, item_id: str, name: str) -> dict[str, Any]:
        if safe_stem(item_id) != item_id:
            raise Memory3DValidationError("Invalid model id")
        if not (self.paths.outputs / f"{item_id}.ply").exists() and not self.find_original_image(item_id):
            raise FileNotFoundError(item_id)
        normalized_name = " ".join((name or "").strip().split())
        if not normalized_name:
            raise Memory3DValidationError("Model name cannot be empty")
        if len(normalized_name) > 80:
            raise Memory3DValidationError("Model name is too long")
        with self.lock:
            metadata = self.read_metadata()
            item_metadata = metadata.get(item_id)
            if not isinstance(item_metadata, dict):
                item_metadata = {}
            item_metadata["name"] = normalized_name
            item_metadata["updated_at"] = utc_now()
            metadata[item_id] = item_metadata
            self.write_metadata(metadata)
            for task in self.tasks.values():
                if task.get("item_id") == item_id:
                    task["name"] = normalized_name
        item = self.gallery_item(item_id)
        return item or {"id": item_id, "name": normalized_name}

    def gallery_item(self, item_id: str) -> Optional[dict[str, Any]]:
        safe_id = safe_stem(item_id)
        if safe_id != item_id:
            return None
        ply_path = self.paths.outputs / f"{item_id}.ply"
        if not ply_path.exists():
            return None
        spz_path = self.paths.outputs / f"{item_id}.spz"
        thumb_path = self.paths.thumbnails / f"{item_id}.jpg"
        image_path = self.find_original_image(item_id)
        timestamps = [ply_path.stat().st_mtime]
        if spz_path.exists():
            timestamps.append(spz_path.stat().st_mtime)
        if image_path:
            timestamps.append(image_path.stat().st_mtime)
        if thumb_path.exists():
            timestamps.append(thumb_path.stat().st_mtime)
        metadata = self.model_metadata(item_id)
        name = str(metadata.get("name") or fallback_display_name(item_id))
        updated_at = datetime.fromtimestamp(max(timestamps), tz=timezone.utc).isoformat()
        return {
            "id": item_id,
            "name": name,
            "model_url": f"/api/v1/memory3d/files/{item_id}.ply",
            "spz_url": f"/api/v1/memory3d/files/{item_id}.spz" if spz_path.exists() else None,
            "image_url": f"/api/v1/memory3d/original/{item_id}" if image_path else None,
            "thumb_url": f"/api/v1/memory3d/thumbnail/{item_id}" if thumb_path.exists() else None,
            "created_at": timestamp_for(ply_path),
            "updated_at": updated_at,
            "status": "ready",
            "size": ply_path.stat().st_size,
            "spz_size": spz_path.stat().st_size if spz_path.exists() else None,
        }

    def find_original_image(self, item_id: str) -> Optional[Path]:
        for ext in self.allowed_extensions:
            path = self.paths.inputs / f"{item_id}{ext}"
            if path.exists():
                return path
        return None

    def resolve_output_file(self, filename: str) -> Path:
        if Path(filename).name != filename or Path(filename).suffix.lower() not in {".ply", ".spz"}:
            raise Memory3DValidationError("Invalid model file")
        path = ensure_child_path(self.paths.outputs, self.paths.outputs / filename)
        if not path.exists():
            raise FileNotFoundError(filename)
        return path

    def resolve_original(self, item_id: str) -> Path:
        path = self.find_original_image(item_id)
        if not path:
            raise FileNotFoundError(item_id)
        return ensure_child_path(self.paths.inputs, path)

    def resolve_thumbnail(self, item_id: str) -> Path:
        path = ensure_child_path(self.paths.thumbnails, self.paths.thumbnails / f"{item_id}.jpg")
        if not path.exists():
            raise FileNotFoundError(item_id)
        return path

    def delete_model(self, item_id: str) -> None:
        if safe_stem(item_id) != item_id:
            raise Memory3DValidationError("Invalid model id")
        with self.lock:
            task_ids = [
                task_id
                for task_id, task in self.tasks.items()
                if task.get("item_id") == item_id
            ]
            for task_id in task_ids:
                process = self.running_processes.pop(task_id, None)
                if process and process.poll() is None:
                    process.terminate()
                self.tasks.pop(task_id, None)

        for path in [
            self.paths.outputs / f"{item_id}.ply",
            self.paths.outputs / f"{item_id}.spz",
            self.paths.thumbnails / f"{item_id}.jpg",
        ]:
            safe_root = self.paths.outputs if path.suffix in {".ply", ".spz"} else self.paths.thumbnails
            resolved = ensure_child_path(safe_root, path)
            if resolved.exists():
                resolved.unlink()
        original = self.find_original_image(item_id)
        if original:
            ensure_child_path(self.paths.inputs, original).unlink()
        with self.lock:
            metadata = self.read_metadata()
            if item_id in metadata:
                metadata.pop(item_id, None)
                self.write_metadata(metadata)

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._worker_loop, daemon=True).start()

    def _worker_loop(self) -> None:
        last_cleanup = time.time()
        while True:
            task_id = self.task_queue.get()
            if task_id is None:
                return
            try:
                self.process_task(task_id)
                if time.time() - last_cleanup > CLEANUP_INTERVAL_SECONDS:
                    self.list_tasks()
                    last_cleanup = time.time()
            finally:
                self.task_queue.task_done()

    def process_task(self, task_id: str) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task or task["status"] == "cancelled":
                return
            task["status"] = "processing"
            task["progress"] = 5
            task["stage"] = "starting"
            task["updated_at"] = utc_now()
            item_id = task["item_id"]
            input_path = self.paths.inputs / task["filename"]

        command = self.build_sharp_command(input_path)
        output_lines: list[str] = []
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self.build_process_env(),
            )
            with self.lock:
                self.running_processes[task_id] = process

            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    if not line:
                        break
                    output_lines.append(line)
                    with self.lock:
                        if self.tasks.get(task_id, {}).get("status") == "cancelled":
                            process.terminate()
                            return
                    self.update_progress(task_id, line)
                process.stdout.close()

            return_code = process.wait()
            if return_code != 0:
                self.fail_task(task_id, "".join(output_lines) or f"Sharp exited with code {return_code}")
                return

            expected_ply = self.paths.outputs / f"{item_id}.ply"
            if not expected_ply.exists():
                self.fail_task(task_id, "Output file not found after Sharp completed.")
                return

            self.try_convert_spz(expected_ply)
            with self.lock:
                task = self.tasks.get(task_id)
                if task and task["status"] != "cancelled":
                    task["status"] = "completed"
                    task["progress"] = 100
                    task["stage"] = "done"
                    task["updated_at"] = utc_now()
        except Exception as exc:
            self.fail_task(task_id, str(exc))
        finally:
            with self.lock:
                self.running_processes.pop(task_id, None)

    def build_sharp_command(self, input_path: Path) -> list[str]:
        device = self.device
        if device == "auto":
            device = "cuda" if shutil.which("nvidia-smi") else "cpu"
        return [
            str(self.resolved_sharp_command or find_sharp_executable(self.sharp_command) or self.sharp_command),
            "predict",
            "-i",
            str(input_path),
            "-o",
            str(self.paths.outputs),
            "-c",
            str(self.checkpoint_path()),
            "--device",
            device,
        ]

    def build_process_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env["TORCH_HOME"] = str(self.model_dir)
        env["HF_HOME"] = str(self.model_dir / "hf")
        env["HF_ENDPOINT"] = os.environ.get("HF_ENDPOINT") or "https://hf-mirror.com"
        return env

    def update_progress(self, task_id: str, line: str) -> None:
        line_lower = line.lower()
        stage_progress = [
            ("download", "downloading", 10),
            ("loading", "loading", 15),
            ("preprocess", "preprocessing", 25),
            ("inference", "inference", 55),
            ("postprocess", "postprocessing", 82),
            ("saving", "saving", 94),
        ]
        with self.lock:
            task = self.tasks.get(task_id)
            if not task or task["status"] == "cancelled":
                return
            for marker, stage, progress in stage_progress:
                if marker in line_lower:
                    task["stage"] = stage
                    task["progress"] = max(task.get("progress", 0), progress)
                    task["updated_at"] = utc_now()
                    return

    def fail_task(self, task_id: str, error: str) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task or task["status"] == "cancelled":
                return
            task["status"] = "failed"
            task["stage"] = "failed"
            task["error"] = error
            task["updated_at"] = utc_now()

    def try_convert_spz(self, ply_path: Path) -> Optional[Path]:
        spz_path = ply_path.with_suffix(".spz")
        if spz_path.exists():
            return spz_path
        try:
            return ply_to_spz(ply_path, spz_path)
        except Exception as exc:
            print(f"[Memory3D] SPZ conversion failed for {ply_path.name}: {exc}")
            return None


_memory3d_service: Memory3DService | None = None


def get_memory3d_service() -> Memory3DService:
    global _memory3d_service
    if _memory3d_service is None:
        _memory3d_service = Memory3DService()
    return _memory3d_service


def reset_memory3d_service_for_tests(service: Memory3DService | None = None) -> None:
    global _memory3d_service
    _memory3d_service = service
