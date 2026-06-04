from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import resolve_path, settings


class RouterPlanCache:
    """Append-only cache for raw LLM router payloads.

    The planner still runs local post-processing after a cache hit, so rule fixes
    apply to old cached entries without requiring cache invalidation.
    """

    def __init__(self, path: Optional[Path] = None, enabled: Optional[bool] = None) -> None:
        self.path = path or Path(resolve_path(settings.LLM_ROUTER_CACHE_PATH))
        self.enabled = settings.LLM_ROUTER_CACHE_ENABLED if enabled is None else enabled
        self.version = str(settings.LLM_ROUTER_CACHE_VERSION or "router-v1")
        self._items: Optional[Dict[str, Dict[str, Any]]] = None

    def get(self, query: str, scenic_slug: Optional[str], model_name: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        return self._load().get(self._key(query, scenic_slug, model_name))

    def set(self, query: str, scenic_slug: Optional[str], model_name: str, payload: Dict[str, Any]) -> None:
        if not self.enabled or not isinstance(payload, dict):
            return
        key = self._key(query, scenic_slug, model_name)
        item = {
            "key": key,
            "version": self.version,
            "model": model_name,
            "scenic_slug": scenic_slug or "",
            "query": str(query or ""),
            "payload": payload,
            "created_at": time.time(),
        }
        self._load()[key] = item
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self._items is not None:
            return self._items
        items: Dict[str, Dict[str, Any]] = {}
        if self.enabled and self.path.exists():
            with open(self.path, "r", encoding="utf-8") as file_obj:
                for raw_line in file_obj:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if item.get("version") != self.version:
                        continue
                    key = str(item.get("key") or "")
                    payload = item.get("payload")
                    if key and isinstance(payload, dict):
                        items[key] = item
        self._items = items
        return items

    def _key(self, query: str, scenic_slug: Optional[str], model_name: str) -> str:
        normalized = {
            "version": self.version,
            "model": str(model_name or ""),
            "scenic_slug": str(scenic_slug or ""),
            "query": str(query or "").strip(),
        }
        raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
