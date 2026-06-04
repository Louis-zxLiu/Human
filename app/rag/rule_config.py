from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from app.core.config import resolve_path


def load_json_config(relative_path: str) -> Dict[str, Any]:
    path = Path(resolve_path(relative_path))
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def nested_value(config: Mapping[str, Any], *keys: str) -> Any:
    value: Any = config
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def term_tuple(config: Mapping[str, Any], *keys: str, fallback: Tuple[str, ...] = ()) -> Tuple[str, ...]:
    value = nested_value(config, *keys)
    if not isinstance(value, list):
        return fallback
    terms = tuple(str(item) for item in value if str(item))
    return terms or fallback


def term_map(config: Mapping[str, Any], *keys: str, fallback: Mapping[str, Tuple[str, ...]]) -> Dict[str, Tuple[str, ...]]:
    value = nested_value(config, *keys)
    if not isinstance(value, Mapping):
        return dict(fallback)
    result: Dict[str, Tuple[str, ...]] = {}
    for map_key, terms in value.items():
        if isinstance(terms, list):
            cleaned = tuple(str(item) for item in terms if str(item))
            if cleaned:
                result[str(map_key)] = cleaned
    return result or dict(fallback)
