import json
import math
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.config import resolve_path
from app.core.runtime import PROJECT_ROOT, merge_runtime_status
from app.rag.pipeline import ScenicRAGPipeline


DEFAULT_DATASET_PATH = PROJECT_ROOT / "tests" / "unified_eval_cases.jsonl"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "unified_eval_report.json"
DEFAULT_MARKDOWN_REPORT_PATH = PROJECT_ROOT / "reports" / "unified_eval_report.md"
DEFAULT_DB_PATH = Path(resolve_path("data/processed/tourist_behavior.db"))

COMPONENT_WEIGHTS = {
    "route": 15.0,
    "source": 20.0,
    "fact": 35.0,
    "expression": 15.0,
    "boundary": 15.0,
}

DEFAULT_THRESHOLDS = {
    "overall": 90.0,
    "docx_structured": 90.0,
    "docx_rag": 90.0,
    "behavior_sql": 90.0,
    "boundary": 85.0,
}

REFUSAL_MARKERS = ("抱歉", "暂时", "无法", "不能", "没有", "未找到", "请补充", "不足")
BEHAVIOR_SOURCE_MARKERS = ("游客行为数据分析", "游客行为数据", "行为数据", "样本游客")
SCENIC_FACT_AGENT_TYPES = {"scenic_fact"}


def load_cases(
    dataset_path: Path,
    suites: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
    tier: str = "full",
) -> List[Dict[str, Any]]:
    suite_filter = {suite.strip() for suite in suites or [] if suite.strip()}
    cases: List[Dict[str, Any]] = []
    with open(dataset_path, "r", encoding="utf-8") as file_obj:
        for line_number, raw_line in enumerate(file_obj, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            case = json.loads(line)
            case["_line_number"] = line_number
            if suite_filter and case.get("suite") not in suite_filter:
                continue
            cases.append(case)
    cases = select_eval_tier(cases, tier=tier)
    if limit:
        cases = cases[:limit]
    return cases


def select_eval_tier(cases: List[Dict[str, Any]], tier: str = "full") -> List[Dict[str, Any]]:
    normalized = str(tier or "full").strip().lower()
    if normalized == "full":
        return cases
    if normalized == "smoke":
        return _balanced_pick(cases, per_category=8, include_hard=True)
    if normalized == "regression":
        return _build_regression_tier(cases) or cases
    raise ValueError(f"unknown eval tier: {tier}")


def _balanced_pick(cases: List[Dict[str, Any]], per_category: int, include_hard: bool) -> List[Dict[str, Any]]:
    by_category: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_category[str(case.get("category") or "UNKNOWN")].append(case)

    selected: List[Dict[str, Any]] = []
    seen = set()
    for category in sorted(by_category):
        bucket = by_category[category]
        preferred = [case for case in bucket if include_hard and case.get("difficulty") == "hard"]
        preferred.extend(case for case in bucket if case not in preferred)
        for case in preferred[:per_category]:
            case_id = str(case.get("id") or "")
            if case_id not in seen:
                selected.append(case)
                seen.add(case_id)
    return selected


def _build_regression_tier(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()
    priority_ids = _recent_failure_ids()

    def add_case(case: Dict[str, Any]) -> None:
        case_id = str(case.get("id") or "")
        if case_id and case_id not in seen:
            selected.append(case)
            seen.add(case_id)

    case_by_id = {str(case.get("id") or ""): case for case in cases}
    for case_id in sorted(priority_ids):
        case = case_by_id.get(case_id)
        if case:
            add_case(case)

    by_category: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_style: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    holdout_cases: List[Dict[str, Any]] = []
    for case in cases:
        by_category[str(case.get("category") or "UNKNOWN")].append(case)
        if case.get("suite") == "holdout":
            holdout_cases.append(case)
        style = str(case.get("rewrite_style") or "").strip()
        if style:
            by_style[style].append(case)

    for category in sorted(by_category):
        hard_cases = [case for case in by_category[category] if case.get("difficulty") == "hard"]
        for case in hard_cases[:10]:
            add_case(case)

    for category in ("BOUNDARY", "FUSION"):
        for case in by_category.get(category, [])[:12]:
            add_case(case)

    for style in sorted(by_style):
        for case in by_style[style][:6]:
            add_case(case)

    for case in holdout_cases[:20]:
        add_case(case)

    return selected


def _recent_failure_ids() -> set[str]:
    candidates = (
        PROJECT_ROOT / ".tmp" / "full1200_failed_54_regression.jsonl",
        PROJECT_ROOT / ".tmp" / "eval_shards" / "shard3_failed_15.jsonl",
    )
    ids: set[str] = set()
    for path in candidates:
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as file_obj:
            for raw_line in file_obj:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                case_id = str(item.get("id") or "")
                if case_id:
                    ids.add(case_id)
    return ids


def execute_gold_sql(sql: Optional[str], db_path: Path = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    if not sql:
        return []

    normalized = re.sub(r"\s+", " ", sql.strip().rstrip(";").lower())
    if not normalized.startswith("select "):
        raise ValueError("gold_sql must be a SELECT statement")
    if any(token in normalized for token in (" insert ", " update ", " delete ", " drop ", " alter ", " pragma ")):
        raise ValueError("gold_sql cannot contain mutating statements")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def score_unified_eval(
    dataset_path: Path = DEFAULT_DATASET_PATH,
    report_path: Optional[Path] = DEFAULT_REPORT_PATH,
    markdown_report_path: Optional[Path] = DEFAULT_MARKDOWN_REPORT_PATH,
    suites: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
    tier: str = "full",
) -> Dict[str, Any]:
    cases = load_cases(dataset_path, suites=suites, limit=limit, tier=tier)
    pipeline = ScenicRAGPipeline()

    scored_cases = []
    category_stats: Dict[str, Dict[str, Any]] = defaultdict(_empty_stats)
    source_stats: Dict[str, Dict[str, Any]] = defaultdict(_empty_stats)
    component_totals = {name: {"score": 0.0, "max": 0.0} for name in COMPONENT_WEIGHTS}
    started_at = time.time()

    for case in cases:
        case_started_at = time.time()
        gold_rows: List[Dict[str, Any]] = []
        gold_error = None
        if case.get("gold_sql"):
            try:
                gold_rows = execute_gold_sql(case["gold_sql"])
            except Exception as exc:
                gold_error = str(exc)

        try:
            result = pipeline.process_query(case["query"])
            runtime_error = None
        except Exception as exc:
            result = {
                "query": case["query"],
                "intent": "ERROR",
                "agent_type": "error",
                "answer": "",
                "response_kind": "exception",
            }
            runtime_error = str(exc)

        case_score = score_case(case, result, gold_rows, gold_error=gold_error, runtime_error=runtime_error)
        case_score["latency_seconds"] = round(time.time() - case_started_at, 3)
        scored_cases.append(case_score)

        category = case.get("category", "UNKNOWN")
        source = case.get("gold_source", "unknown")
        _merge_case_stats(category_stats[category], case_score)
        _merge_case_stats(source_stats[source], case_score)
        for component, detail in case_score["components"].items():
            component_totals[component]["score"] += detail["score"]
            component_totals[component]["max"] += detail["max"]

    total_score = sum(item["score"] for item in scored_cases)
    total_max = sum(item["max_score"] for item in scored_cases)
    overall = _percent(total_score, total_max)
    failed_cases = [case for case in scored_cases if not case["passed"]]
    payload = {
        "ok": _passes_thresholds(overall, source_stats),
        "dataset": str(dataset_path),
        "tier": tier,
        "case_count": len(scored_cases),
        "overall_score": overall,
        "total_points": round(total_score, 2),
        "max_points": round(total_max, 2),
        "thresholds": DEFAULT_THRESHOLDS,
        "elapsed_seconds": round(time.time() - started_at, 3),
        "by_category": _finalize_stats(category_stats),
        "by_gold_source": _finalize_stats(source_stats),
        "by_component": {
            name: {
                "score": round(values["score"], 2),
                "max": round(values["max"], 2),
                "accuracy": _percent(values["score"], values["max"]),
            }
            for name, values in component_totals.items()
        },
        "failure_count": len(failed_cases),
        "failure_sample_count": min(len(failed_cases), 50),
        "failures": failed_cases[:50],
        "confusions": _collect_confusions(scored_cases),
        "cases": scored_cases,
    }

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if markdown_report_path:
        markdown_report_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_report_path.write_text(render_markdown_report(payload), encoding="utf-8")

    merge_runtime_status({"last_unified_eval": _compact_runtime_payload(payload)})
    return payload


def score_case(
    case: Dict[str, Any],
    result: Dict[str, Any],
    gold_rows: List[Dict[str, Any]],
    gold_error: Optional[str] = None,
    runtime_error: Optional[str] = None,
) -> Dict[str, Any]:
    answer = str(result.get("answer") or "")
    components = {
        "route": _score_route(case, result),
        "source": _score_source(case, result, answer),
        "fact": _score_fact(case, result, answer, gold_rows, gold_error),
        "expression": _score_expression(case, answer),
        "boundary": _score_boundary(case, result, answer),
    }
    total = sum(detail["score"] for detail in components.values())
    max_score = sum(detail["max"] for detail in components.values())
    score = _percent(total, max_score)
    passed = score >= float(case.get("pass_score", 90.0))
    failure_reasons = [
        note
        for detail in components.values()
        for note in detail.get("notes", [])
        if note
    ]
    if gold_error:
        failure_reasons.append(f"gold_sql error: {gold_error}")
    if runtime_error:
        failure_reasons.append(f"runtime error: {runtime_error}")

    return {
        "id": case.get("id"),
        "suite": case.get("suite"),
        "category": case.get("category"),
        "gold_source": case.get("gold_source"),
        "difficulty": case.get("difficulty"),
        "query": case.get("query"),
        "expected_intent": case.get("expected_intent"),
        "actual_intent": result.get("intent"),
        "agent_type": result.get("agent_type"),
        "response_kind": result.get("response_kind"),
        "answer_preview": answer[:260],
        "score": score,
        "points": round(total, 2),
        "max_score": round(max_score, 2),
        "passed": passed,
        "components": components,
        "gold_rows_preview": gold_rows[:3],
        "failure_reasons": failure_reasons[:12],
    }


def _score_route(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    if case.get("gold_source") == "boundary" and str(result.get("response_kind") or "").startswith("refused"):
        return _component("route", 1.0, [])

    expected = case.get("expected_intent")
    if not expected:
        return _component("route", 1.0, [])
    actual = result.get("intent")
    if actual == expected:
        return _component("route", 1.0, [])
    return _component("route", 0.0, [f"intent mismatch: expected {expected}, got {actual}"])


def _score_source(case: Dict[str, Any], result: Dict[str, Any], answer: str) -> Dict[str, Any]:
    source = case.get("gold_source")
    intent = result.get("intent")
    agent_type = result.get("agent_type")
    notes = []
    parts: List[float] = []

    if source == "behavior_sql":
        parts.append(1.0 if intent == "ANALYTICS" else 0.0)
        parts.append(1.0 if any(marker in answer for marker in BEHAVIOR_SOURCE_MARKERS) else 0.0)
        parts.append(1.0 if agent_type == "behavior_analytics" else 0.0)
        if parts[0] == 0:
            notes.append("behavior question did not route to ANALYTICS")
        if parts[1] == 0:
            notes.append("behavior answer did not state data source")
    elif source in {"docx_structured", "docx_rag"}:
        parts.append(1.0 if intent == "FACT" else 0.0)
        parts.append(1.0 if agent_type in SCENIC_FACT_AGENT_TYPES else 0.0)
        parts.append(1.0 if "游客行为数据" not in answer else 0.0)
        if parts[0] == 0:
            notes.append("DOCX fact question did not route to FACT")
        if parts[2] == 0:
            notes.append("DOCX fact answer mixed in behavior-data wording")
    elif source == "fusion":
        recommendation = result.get("recommendation") or {}
        parts.append(1.0 if intent == "RECOMMEND" else 0.0)
        parts.append(1.0 if recommendation else 0.0)
        parts.append(1.0 if "推荐路线" in answer or recommendation.get("route_items") else 0.0)
        if parts[0] == 0:
            notes.append("fusion question did not route to RECOMMEND")
    elif source == "boundary":
        parts.append(1.0 if _looks_like_refusal(answer, result) else 0.0)
        parts.append(1.0 if not _contains_any(answer, BEHAVIOR_SOURCE_MARKERS) else 0.5)
        parts.append(1.0)
        if parts[0] == 0:
            notes.append("boundary answer did not clearly refuse or ask for more evidence")
    else:
        parts.append(1.0)

    return _component("source", _average(parts), notes)


def _score_fact(
    case: Dict[str, Any],
    result: Dict[str, Any],
    answer: str,
    gold_rows: List[Dict[str, Any]],
    gold_error: Optional[str],
) -> Dict[str, Any]:
    source = case.get("gold_source")
    notes = []
    scores: List[float] = []

    if case.get("must_include"):
        matched = [term for term in case["must_include"] if str(term) in answer]
        score = len(matched) / len(case["must_include"])
        scores.append(score)
        if score < 1.0:
            missing = [term for term in case["must_include"] if str(term) not in answer]
            notes.append(f"missing required terms: {missing[:5]}")

    if gold_error:
        scores.append(0.0)
        notes.append("gold_sql failed")
    elif gold_rows:
        sql_score, sql_notes = _score_gold_rows(case, answer, gold_rows)
        scores.append(sql_score)
        notes.extend(sql_notes)

    expected = case.get("expected") or {}
    if source == "fusion":
        scores.append(_score_recommendation_expected(expected, result, answer, notes))
    elif source == "boundary":
        scores.append(1.0 if _looks_like_refusal(answer, result) else 0.0)

    if not scores:
        scores.append(1.0 if answer.strip() else 0.0)
        if not answer.strip():
            notes.append("empty answer")
    return _component("fact", _average(scores), notes)


def _score_expression(case: Dict[str, Any], answer: str) -> Dict[str, Any]:
    notes = []
    parts = [1.0 if answer.strip() else 0.0]
    source = case.get("gold_source")
    if source == "behavior_sql":
        has_source = any(marker in answer for marker in BEHAVIOR_SOURCE_MARKERS)
        parts.append(1.0 if has_source else 0.0)
        if not has_source:
            notes.append("missing behavior-data source statement")
    elif source == "fusion":
        parts.append(1.0 if "预计" in answer or "时长" in answer else 0.0)
        parts.append(1.0 if "讲解重点" in answer or "重点" in answer else 0.0)
    elif source in {"docx_structured", "docx_rag"}:
        parts.append(1.0 if len(answer) >= 12 else 0.0)
    elif source == "boundary":
        parts.append(1.0 if _looks_like_refusal(answer, {}) else 0.0)
    return _component("expression", _average(parts), notes)


def _score_boundary(case: Dict[str, Any], result: Dict[str, Any], answer: str) -> Dict[str, Any]:
    notes = []
    parts = []
    forbidden = [term for term in case.get("must_not_include", []) if str(term) in answer]
    if forbidden:
        notes.append(f"forbidden terms appeared: {forbidden[:5]}")
    parts.append(1.0 if not forbidden else 0.0)

    if case.get("gold_source") == "boundary":
        refused = _looks_like_refusal(answer, result)
        parts.append(1.0 if refused else 0.0)
        if not refused:
            notes.append("boundary case was not refused")
    else:
        if case.get("answer_type") not in {"refusal", "boundary"}:
            parts.append(1.0 if not _looks_like_refusal(answer, result) else 0.5)
    return _component("boundary", _average(parts), notes)


def _score_gold_rows(case: Dict[str, Any], answer: str, rows: List[Dict[str, Any]]) -> Tuple[float, List[str]]:
    answer_type = case.get("answer_type", "")
    notes = []
    if answer_type in {"numeric", "count", "average", "percentage"}:
        return _score_numeric_answer(case, answer, rows)
    if answer_type in {"top_list", "grouped_list", "ranking"}:
        return _score_entity_list(answer, rows)
    return _score_text_rows(answer, rows)


def _score_numeric_answer(case: Dict[str, Any], answer: str, rows: List[Dict[str, Any]]) -> Tuple[float, List[str]]:
    expected_numbers = _numbers_from_rows(rows)
    actual_numbers = _extract_numbers(answer)
    tolerance = float(case.get("tolerance", 0.5))
    if not expected_numbers:
        return 1.0, []
    if not actual_numbers:
        return 0.0, ["no numeric value found in answer"]

    best_scores = []
    for expected in expected_numbers:
        best_delta = min(abs(actual - expected) for actual in actual_numbers)
        best_scores.append(1.0 if best_delta <= tolerance else max(0.0, 1.0 - best_delta / max(abs(expected), 1.0)))
    score = sum(best_scores) / len(best_scores)
    notes = [] if score >= 0.9 else [f"numeric mismatch: expected {expected_numbers[:5]}, got {actual_numbers[:8]}"]
    return score, notes


def _score_entity_list(answer: str, rows: List[Dict[str, Any]]) -> Tuple[float, List[str]]:
    expected_terms = []
    for row in rows[:5]:
        for value in row.values():
            if isinstance(value, str) and value and not _is_number_like(value):
                expected_terms.append(value)
                break
    if not expected_terms:
        return _score_text_rows(answer, rows)

    matched = [term for term in expected_terms if term in answer]
    score = len(matched) / len(expected_terms)
    notes = [] if score >= 0.8 else [f"missing ranked terms: {[term for term in expected_terms if term not in answer][:5]}"]
    return score, notes


def _score_text_rows(answer: str, rows: List[Dict[str, Any]]) -> Tuple[float, List[str]]:
    terms = _salient_terms_from_rows(rows)
    if not terms:
        return 1.0, []
    matched = [term for term in terms if term in answer]
    required = max(1, min(int(math.ceil(len(terms) * 0.35)), 5))
    score = min(1.0, len(matched) / required)
    notes = [] if score >= 0.9 else [f"missing evidence terms: {[term for term in terms if term not in answer][:8]}"]
    return score, notes


def _score_recommendation_expected(
    expected: Dict[str, Any],
    result: Dict[str, Any],
    answer: str,
    notes: List[str],
) -> float:
    recommendation = result.get("recommendation") or {}
    route_items = recommendation.get("route_items") or []
    route_names = [item.get("name", "") for item in route_items if isinstance(item, dict)]
    haystack = answer + " ".join(route_names) + str(recommendation.get("label") or "")
    parts = []

    label = expected.get("label")
    if label:
        parts.append(1.0 if label in haystack else 0.0)
        if label not in haystack:
            notes.append(f"missing recommendation label: {label}")

    route_contains = expected.get("route_contains") or []
    if route_contains:
        matched = [name for name in route_contains if name in haystack]
        parts.append(len(matched) / len(route_contains))
        if len(matched) < len(route_contains):
            notes.append(f"missing route nodes: {[name for name in route_contains if name not in haystack]}")

    min_items = int(expected.get("min_route_items", 3))
    parts.append(1.0 if len(route_names) >= min_items or answer.count("->") >= max(min_items - 1, 1) else 0.0)
    parts.append(1.0 if "预计" in answer or "时长" in answer else 0.0)
    parts.append(1.0 if "讲解重点" in answer or "重点" in answer else 0.0)
    return _average(parts)


def _component(name: str, ratio: float, notes: List[str]) -> Dict[str, Any]:
    max_score = COMPONENT_WEIGHTS[name]
    bounded = max(0.0, min(1.0, ratio))
    return {
        "score": round(max_score * bounded, 2),
        "max": max_score,
        "accuracy": round(bounded * 100, 2),
        "notes": notes,
    }


def _numbers_from_rows(rows: List[Dict[str, Any]]) -> List[float]:
    numbers = []
    for row in rows:
        for value in row.values():
            parsed = _to_float(value)
            if parsed is not None:
                numbers.append(parsed)
    return numbers[:8]


def _extract_numbers(text: str) -> List[float]:
    pattern = r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?"
    return [float(match.replace(",", "")) for match in re.findall(pattern, text)]


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and _is_number_like(value):
        return float(value)
    return None


def _is_number_like(value: str) -> bool:
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", str(value).strip()))


def _salient_terms_from_rows(rows: List[Dict[str, Any]]) -> List[str]:
    terms: List[str] = []
    for row in rows[:3]:
        for value in row.values():
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            if _is_number_like(text):
                terms.append(text)
                continue
            for term in re.findall(r"[\u4e00-\u9fffA-Za-z0-9.]+", text):
                if len(term) >= 2 and term not in terms:
                    terms.append(term)
                if len(terms) >= 12:
                    return terms
    return terms


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def _looks_like_refusal(answer: str, result: Dict[str, Any]) -> bool:
    response_kind = str(result.get("response_kind") or "")
    if response_kind.startswith("refused"):
        return True
    return any(marker in answer for marker in REFUSAL_MARKERS)


def _average(values: Sequence[float]) -> float:
    if not values:
        return 1.0
    return sum(values) / len(values)


def _percent(score: float, max_score: float) -> float:
    if max_score <= 0:
        return 0.0
    return round(score / max_score * 100, 2)


def _empty_stats() -> Dict[str, Any]:
    return {
        "count": 0,
        "passed": 0,
        "score": 0.0,
        "max": 0.0,
    }


def _merge_case_stats(stats: Dict[str, Any], case_score: Dict[str, Any]) -> None:
    stats["count"] += 1
    stats["passed"] += 1 if case_score["passed"] else 0
    stats["score"] += case_score["points"]
    stats["max"] += case_score["max_score"]


def _finalize_stats(stats_by_key: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        key: {
            "count": values["count"],
            "passed": values["passed"],
            "accuracy": _percent(values["score"], values["max"]),
            "pass_rate": _percent(values["passed"], values["count"]),
            "points": round(values["score"], 2),
            "max_points": round(values["max"], 2),
        }
        for key, values in sorted(stats_by_key.items())
    }


def _passes_thresholds(overall: float, source_stats: Dict[str, Dict[str, Any]]) -> bool:
    if overall < DEFAULT_THRESHOLDS["overall"]:
        return False
    finalized = _finalize_stats(source_stats)
    for source, threshold in DEFAULT_THRESHOLDS.items():
        if source == "overall" or source not in finalized:
            continue
        if finalized[source]["accuracy"] < threshold:
            return False
    return True


def _collect_confusions(scored_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    confusions = []
    for case in scored_cases:
        if case.get("expected_intent") != case.get("actual_intent"):
            confusions.append(
                {
                    "id": case.get("id"),
                    "query": case.get("query"),
                    "expected_intent": case.get("expected_intent"),
                    "actual_intent": case.get("actual_intent"),
                    "gold_source": case.get("gold_source"),
                }
            )
    return confusions[:50]


def _compact_runtime_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": payload["ok"],
        "dataset": payload["dataset"],
        "tier": payload.get("tier", "full"),
        "case_count": payload["case_count"],
        "overall_score": payload["overall_score"],
        "by_gold_source": payload["by_gold_source"],
        "failure_count": payload.get("failure_count", len(payload["failures"])),
        "failure_sample_count": payload.get("failure_sample_count", len(payload["failures"])),
    }


def render_markdown_report(payload: Dict[str, Any]) -> str:
    lines = [
        "# 统一自测集评测报告",
        "",
        f"- 数据集：`{payload['dataset']}`",
        f"- 评测层级：{payload.get('tier', 'full')}",
        f"- 样例数：{payload['case_count']}",
        f"- 总分：{payload['overall_score']} / 100",
        f"- 结果：{'通过' if payload['ok'] else '未通过'}",
        f"- 待优化样例数：{payload.get('failure_count', len(payload['failures']))}",
        f"- 报告展示失败样例数：{payload.get('failure_sample_count', len(payload['failures']))}",
        f"- 耗时：{payload['elapsed_seconds']} 秒",
        "",
        "## 按数据源统计",
        "",
        "| 数据源 | 样例数 | 通过数 | 得分 | 通过率 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for source, stats in payload["by_gold_source"].items():
        lines.append(
            f"| {source} | {stats['count']} | {stats['passed']} | "
            f"{stats['accuracy']} | {stats['pass_rate']} |"
        )

    lines.extend(
        [
            "",
            "## 按评分项统计",
            "",
            "| 评分项 | 得分 |",
            "| --- | ---: |",
        ]
    )
    for component, stats in payload["by_component"].items():
        lines.append(f"| {component} | {stats['accuracy']} |")

    lines.extend(["", "## 失败样例", ""])
    if not payload["failures"]:
        lines.append("暂无失败样例。")
    for failure in payload["failures"][:20]:
        reasons = "；".join(failure.get("failure_reasons") or [])
        lines.extend(
            [
                f"### {failure.get('id')} ({failure.get('score')})",
                f"- 问题：{failure.get('query')}",
                f"- 期望/实际意图：{failure.get('expected_intent')} / {failure.get('actual_intent')}",
                f"- 原因：{reasons or '未命中通过线'}",
                f"- 回答摘录：{failure.get('answer_preview')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
