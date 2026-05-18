from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def make_evidence(
    source_type: str,
    source_name: str,
    *,
    entity: Optional[str] = None,
    field: Optional[str] = None,
    snippet: Optional[str] = None,
    score: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source_type": source_type,
        "source_name": source_name,
    }
    if entity:
        payload["entity"] = entity
    if field:
        payload["field"] = field
    if snippet:
        payload["snippet"] = str(snippet).strip()[:240]
    if score is not None:
        payload["score"] = round(float(score), 4)
    if metadata:
        payload["metadata"] = metadata
    return payload


def make_refusal(
    reason: str,
    *,
    message: Optional[str] = None,
    suggested_queries: Optional[Iterable[str]] = None,
    allowed_sources: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    if message:
        payload["message"] = message
    if suggested_queries:
        payload["suggested_queries"] = [str(item) for item in suggested_queries if str(item).strip()]
    if allowed_sources:
        payload["allowed_sources"] = [str(item) for item in allowed_sources if str(item).strip()]
    return payload


def compact_rows(rows: Iterable[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    trimmed: List[Dict[str, Any]] = []
    for row in list(rows)[:limit]:
        compact_row: Dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, str):
                compact_row[key] = value[:120]
            else:
                compact_row[key] = value
        trimmed.append(compact_row)
    return trimmed
