from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


CORE_RUNTIME_IMPORT_CHECKS = [
    ("pydantic_settings", "import pydantic_settings"),
    ("pydantic", "import pydantic"),
    ("numpy", "import numpy"),
    ("pandas", "import pandas"),
    ("openpyxl", "import openpyxl"),
    ("lxml.etree", "from lxml import etree"),
    ("python-docx", "import docx"),
    ("fastapi", "import fastapi"),
]

FULL_RUNTIME_IMPORT_CHECKS = CORE_RUNTIME_IMPORT_CHECKS + [
    ("torch", "import torch"),
    ("langchain", "import langchain"),
    ("langchain_community", "import langchain_community"),
    ("langchain_openai", "import langchain_openai"),
    ("chromadb", "import chromadb"),
    ("sentence_transformers", "import sentence_transformers"),
    ("huggingface_hub", "import huggingface_hub"),
    ("whisper", "import whisper"),
    ("edge_tts", "import edge_tts"),
]


def checks_for_profile(profile: str) -> list[tuple[str, str]]:
    if profile == "core":
        return CORE_RUNTIME_IMPORT_CHECKS
    if profile == "full":
        return FULL_RUNTIME_IMPORT_CHECKS
    raise ValueError(f"Unsupported runtime health profile: {profile}")


def collect_runtime_health_report(project_root: str | Path, profile: str = "full") -> Dict[str, Any]:
    root = Path(project_root)
    checks: List[Dict[str, Any]] = []

    for label, statement in checks_for_profile(profile):
        result = subprocess.run(
            [sys.executable, "-c", statement],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        detail = (result.stderr or result.stdout).strip()
        checks.append(
            {
                "label": label,
                "ok": result.returncode == 0,
                "detail": detail or None,
            }
        )

    failures = [check for check in checks if not check["ok"]]
    return {
        "ok": not failures,
        "profile": profile,
        "checks": checks,
        "failures": failures,
    }


def runtime_failure_messages(report: Dict[str, Any]) -> List[str]:
    messages: List[str] = []
    for failure in report.get("failures", []):
        detail = failure.get("detail") or "unknown import error"
        messages.append(f"Runtime import check failed for {failure['label']}: {detail}")
    return messages
