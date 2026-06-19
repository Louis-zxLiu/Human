from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit("usage: merge_eval_shards.py OUT_JSON OUT_MD SHARD_JSON...")
    out_json = Path(sys.argv[1])
    out_md = Path(sys.argv[2])
    shard_paths = [Path(item) for item in sys.argv[3:]]
    payload = merge_shards(shard_paths)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    from app.tasks.unified_eval import render_markdown_report

    out_md.write_text(render_markdown_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": payload["ok"],
                "case_count": payload["case_count"],
                "overall_score": payload["overall_score"],
                "failure_count": payload["failure_count"],
                "elapsed_seconds": payload["elapsed_seconds"],
                "by_gold_source": payload["by_gold_source"],
            },
            ensure_ascii=False,
        )
    )


def merge_shards(paths: Iterable[Path]) -> Dict[str, Any]:
    shard_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    cases: List[Dict[str, Any]] = []
    elapsed = 0.0
    dataset = ""
    thresholds = {}
    by_component_points: Dict[str, Dict[str, float]] = defaultdict(lambda: {"score": 0.0, "max": 0.0})
    for payload in shard_payloads:
        cases.extend(payload.get("cases") or [])
        elapsed = max(elapsed, float(payload.get("elapsed_seconds") or 0.0))
        dataset = dataset or str(payload.get("dataset") or "")
        thresholds = thresholds or dict(payload.get("thresholds") or {})
        for case in payload.get("cases") or []:
            for name, detail in (case.get("components") or {}).items():
                by_component_points[name]["score"] += float(detail.get("score") or 0.0)
                by_component_points[name]["max"] += float(detail.get("max") or 0.0)

    cases.sort(key=lambda item: str(item.get("id") or ""))
    total_score = sum(float(case.get("points") or 0.0) for case in cases)
    total_max = sum(float(case.get("max_score") or 0.0) for case in cases)
    failures = [case for case in cases if not case.get("passed")]
    by_category = _stats(cases, "category")
    by_gold_source = _stats(cases, "gold_source")
    by_component = {
        name: {
            "score": round(values["score"], 2),
            "max": round(values["max"], 2),
            "accuracy": _percent(values["score"], values["max"]),
        }
        for name, values in sorted(by_component_points.items())
    }
    payload = {
        "ok": _passes_thresholds(_percent(total_score, total_max), by_gold_source, thresholds),
        "dataset": dataset,
        "tier": "full",
        "case_count": len(cases),
        "overall_score": _percent(total_score, total_max),
        "total_points": round(total_score, 2),
        "max_points": round(total_max, 2),
        "thresholds": thresholds,
        "elapsed_seconds": round(elapsed, 3),
        "by_category": by_category,
        "by_gold_source": by_gold_source,
        "by_component": by_component,
        "failure_count": len(failures),
        "failure_sample_count": min(len(failures), 50),
        "failures": failures[:50],
        "confusions": _confusions(cases),
        "cases": cases,
    }
    return payload


def _stats(cases: List[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "passed": 0, "score": 0.0, "max": 0.0})
    for case in cases:
        name = str(case.get(key) or "UNKNOWN")
        bucket = buckets[name]
        bucket["count"] += 1
        bucket["passed"] += 1 if case.get("passed") else 0
        bucket["score"] += float(case.get("points") or 0.0)
        bucket["max"] += float(case.get("max_score") or 0.0)
    return {
        name: {
            "count": values["count"],
            "passed": values["passed"],
            "accuracy": _percent(values["score"], values["max"]),
            "pass_rate": _percent(values["passed"], values["count"]),
            "points": round(values["score"], 2),
            "max_points": round(values["max"], 2),
        }
        for name, values in sorted(buckets.items())
    }


def _passes_thresholds(overall: float, source_stats: Dict[str, Dict[str, Any]], thresholds: Dict[str, Any]) -> bool:
    if overall < float(thresholds.get("overall", 90.0)):
        return False
    for source, threshold in thresholds.items():
        if source == "overall" or source not in source_stats:
            continue
        if source_stats[source]["accuracy"] < float(threshold):
            return False
    return True


def _confusions(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = []
    for case in cases:
        if case.get("expected_intent") != case.get("actual_intent"):
            items.append(
                {
                    "id": case.get("id"),
                    "query": case.get("query"),
                    "expected_intent": case.get("expected_intent"),
                    "actual_intent": case.get("actual_intent"),
                    "gold_source": case.get("gold_source"),
                }
            )
    return items[:50]


def _percent(score: float, max_score: float) -> float:
    if max_score <= 0:
        return 0.0
    return round(score / max_score * 100, 2)


if __name__ == "__main__":
    main()
