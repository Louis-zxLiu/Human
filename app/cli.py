import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List

from app.core.runtime_health import collect_runtime_health_report
from app.core.runtime import CONDA_ENV_PREFIX, PROJECT_ROOT


FRONTEND_DIR = PROJECT_ROOT / "frontend"
DEFAULT_TORCH_WHL_INDEX_URL = "https://download.pytorch.org/whl/cu126"
DEFAULT_WHISPER_VERSION = "openai-whisper==20250625"


def print_json(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def run_subprocess(command: List[str], cwd: Path | None = None) -> int:
    process = subprocess.run(command, cwd=str(cwd or PROJECT_ROOT))
    return process.returncode


def get_torch_whl_index_url() -> str:
    return os.environ.get("TORCH_WHL_INDEX_URL") or DEFAULT_TORCH_WHL_INDEX_URL


def get_whisper_requirement() -> str:
    return os.environ.get("OPENAI_WHISPER_REQUIREMENT") or DEFAULT_WHISPER_VERSION


def runtime_health_payload(profile: str = "full") -> dict:
    report = collect_runtime_health_report(PROJECT_ROOT, profile=profile)
    if report["ok"]:
        return {"ok": True, "checks": report["checks"]}
    return {
        "ok": False,
        "error": "Runtime dependency validation failed.",
        "profile": report["profile"],
        "checks": report["checks"],
        "failures": report["failures"],
        "hint": "The current D:/Human/env is not a healthy runnable environment. Remove D:/Human/env and rerun bootstrap_windows.bat.",
    }


def ensure_runtime_health(profile: str = "full") -> bool:
    payload = runtime_health_payload(profile=profile)
    if payload["ok"]:
        return True
    print_json(payload)
    return False


def ensure_gpu_torch_runtime() -> int:
    report = collect_runtime_health_report(PROJECT_ROOT, profile="full")
    labels = {failure["label"] for failure in report["failures"]}
    if "torch" not in labels:
        return 0

    torch_index_url = get_torch_whl_index_url()
    return run_subprocess(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "torch",
            "torchvision",
            "torchaudio",
            "--index-url",
            torch_index_url,
        ]
    )


def ensure_whisper_runtime() -> int:
    report = collect_runtime_health_report(PROJECT_ROOT, profile="full")
    labels = {failure["label"] for failure in report["failures"]}
    if "whisper" not in labels:
        return 0

    return run_subprocess(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-build-isolation",
            get_whisper_requirement(),
            "-i",
            os.environ.get("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple"),
        ]
    )


def in_expected_conda_env() -> bool:
    conda_prefix = os.environ.get("CONDA_PREFIX")
    return bool(conda_prefix) and Path(conda_prefix).resolve() == CONDA_ENV_PREFIX.resolve()


def ensure_runtime_env() -> None:
    if not in_expected_conda_env():
        raise RuntimeError(
            f"Current Python is not running inside the project conda env prefix `{CONDA_ENV_PREFIX}`. "
            f'Use `conda run -p "{CONDA_ENV_PREFIX}" python -m app.cli ...` or activate the env first.'
        )


def cmd_bootstrap(_: argparse.Namespace) -> int:
    ensure_runtime_env()
    env_example = PROJECT_ROOT / ".env.example"
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists() and env_example.exists():
        env_file.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")

    code = ensure_gpu_torch_runtime()
    if code != 0:
        return code

    code = ensure_whisper_runtime()
    if code != 0:
        return code

    if not ensure_runtime_health(profile="full"):
        return 1

    code = run_subprocess([sys.executable, "-m", "app.cli", "_download-models"])
    if code != 0:
        return code
    run_subprocess([sys.executable, "-m", "app.cli", "doctor"])
    return 0


def cmd_download_models(_: argparse.Namespace) -> int:
    from app.tasks.download_models import download_required_models
    from app.tasks.doctor import collect_doctor_report

    ensure_runtime_env()
    payload = download_required_models()
    print_json(payload)
    collect_doctor_report()
    return 0 if payload["ok"] else 1


def cmd_doctor(_: argparse.Namespace) -> int:
    from app.tasks.doctor import collect_doctor_report

    payload = collect_doctor_report()
    print_json(payload)
    return 0 if payload["ok"] else 1


def cmd_prepare_data(_: argparse.Namespace) -> int:
    ensure_runtime_env()
    if not ensure_runtime_health(profile="full"):
        return 1
    from app.tasks.prepare_fact_db import prepare_fact_db
    from app.tasks.prepare_behavior_db import prepare_behavior_db
    from app.tasks.doctor import collect_doctor_report

    payload = {
        "fact_db": prepare_fact_db(),
        "behavior_db": prepare_behavior_db(),
    }
    collect_doctor_report()
    print_json(payload)
    return 0


def cmd_prepare_kb(_: argparse.Namespace) -> int:
    ensure_runtime_env()
    if not ensure_runtime_health(profile="full"):
        return 1
    from app.tasks.prepare_vector_kb import prepare_vector_kb
    from app.tasks.doctor import collect_doctor_report

    payload = prepare_vector_kb()
    collect_doctor_report()
    print_json(payload)
    return 0


def cmd_eval(_: argparse.Namespace) -> int:
    ensure_runtime_env()
    if not ensure_runtime_health(profile="full"):
        return 1
    from app.tasks.eval import run_eval_suite

    payload = run_eval_suite()
    print_json(payload)
    return 0


def cmd_runtime_health(args: argparse.Namespace) -> int:
    payload = runtime_health_payload(profile=args.profile)
    if not args.quiet or not payload["ok"]:
        print_json(payload)
    return 0 if payload["ok"] else 1


def cmd_build_frontend(_: argparse.Namespace) -> int:
    ensure_runtime_env()
    if not FRONTEND_DIR.exists():
        print_json({"ok": False, "error": "frontend directory is missing"})
        return 1

    npm = "npm.cmd" if os.name == "nt" else "npm"
    try:
        code = run_subprocess([npm, "install"], cwd=FRONTEND_DIR)
    except FileNotFoundError:
        print_json({"ok": False, "error": "npm was not found. Ensure nodejs from environment.yml is available."})
        return 1
    if code != 0:
        return code
    code = run_subprocess([npm, "run", "build"], cwd=FRONTEND_DIR)
    if code != 0:
        return code

    from app.core.runtime import frontend_build_ready, merge_runtime_status

    merge_runtime_status({"frontend_built": frontend_build_ready()})
    print_json({"ok": frontend_build_ready(), "dist_ready": frontend_build_ready()})
    return 0 if frontend_build_ready() else 1


def cmd_start(args: argparse.Namespace) -> int:
    ensure_runtime_env()
    if not ensure_runtime_health(profile="full"):
        return 1
    code = run_subprocess([sys.executable, "-m", "app.cli", "doctor"])
    if code != 0:
        return code
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if args.reload:
        command.append("--reload")
    return run_subprocess(command)


def cmd_dev(args: argparse.Namespace) -> int:
    ensure_runtime_env()
    if not ensure_runtime_health(profile="full"):
        return 1
    npm = "npm.cmd" if os.name == "nt" else "npm"
    try:
        if not (FRONTEND_DIR / "node_modules").exists():
            code = run_subprocess([npm, "install"], cwd=FRONTEND_DIR)
            if code != 0:
                return code
        backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", args.backend_host, "--port", str(args.backend_port), "--reload"],
            cwd=str(PROJECT_ROOT),
        )
        frontend = subprocess.Popen(
            [npm, "run", "dev", "--", "--host", args.frontend_host, "--port", str(args.frontend_port)],
            cwd=str(FRONTEND_DIR),
        )
    except FileNotFoundError:
        print_json({"ok": False, "error": "npm was not found. Ensure nodejs from environment.yml is available."})
        return 1
    try:
        frontend.wait()
    finally:
        backend.terminate()
        frontend.terminate()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified engineering CLI for the Human project.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap")
    bootstrap.set_defaults(func=cmd_bootstrap)

    doctor = subparsers.add_parser("doctor")
    doctor.set_defaults(func=cmd_doctor)

    prepare_data = subparsers.add_parser("prepare-data")
    prepare_data.set_defaults(func=cmd_prepare_data)

    prepare_kb = subparsers.add_parser("prepare-kb")
    prepare_kb.set_defaults(func=cmd_prepare_kb)

    eval_parser = subparsers.add_parser("eval")
    eval_parser.set_defaults(func=cmd_eval)

    runtime_health = subparsers.add_parser("runtime-health")
    runtime_health.add_argument("--profile", choices=["core", "full"], default="full")
    runtime_health.add_argument("--quiet", action="store_true")
    runtime_health.set_defaults(func=cmd_runtime_health)

    build_frontend = subparsers.add_parser("build-frontend")
    build_frontend.set_defaults(func=cmd_build_frontend)

    start = subparsers.add_parser("start")
    start.add_argument("--host", default="0.0.0.0")
    start.add_argument("--port", type=int, default=8000)
    start.add_argument("--reload", action="store_true")
    start.set_defaults(func=cmd_start)

    dev = subparsers.add_parser("dev")
    dev.add_argument("--backend-host", default="0.0.0.0")
    dev.add_argument("--backend-port", type=int, default=8000)
    dev.add_argument("--frontend-host", default="0.0.0.0")
    dev.add_argument("--frontend-port", type=int, default=5173)
    dev.set_defaults(func=cmd_dev)

    hidden = subparsers.add_parser("_download-models")
    hidden.set_defaults(func=cmd_download_models)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
