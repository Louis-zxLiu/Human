from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.runtime import PROJECT_ROOT
from app.rag.llm_client import get_llm_client, llm_is_configured
from app.tasks.generate_unified_eval import CASE_FIELD_ORDER, DEFAULT_OUTPUT_PATH, validate_cases


DEFAULT_REWRITTEN_OUTPUT_PATH = PROJECT_ROOT / "tests" / "unified_eval_cases_llm_rewritten.jsonl"
DEFAULT_REWRITE_CACHE_PATH = PROJECT_ROOT / ".cache" / "unified_eval_rewrites.jsonl"
DEFAULT_REWRITE_REPORT_PATH = PROJECT_ROOT / "reports" / "unified_eval_rewrite_report.json"

REWRITTEN_CASE_FIELD_ORDER = CASE_FIELD_ORDER + [
    "rewrite_of",
    "rewrite_style",
    "rewrite_notes",
]

STYLE_CYCLE = [
    "口语化游客提问",
    "评委追问",
    "省略数据源的自然问法",
    "带轻微上下文的追问",
    "更短的移动端问法",
    "更正式的验收问法",
]

CATEGORY_GUIDANCE = {
    "DOCX_STRUCTURED": "保留景点名称和所问属性，不要改变为数据分析题。",
    "DOCX_RAG": "保留实体和主题，问法可以更像讲解员备稿或评委追问。",
    "BEHAVIOR_SQL": "保留所有筛选条件、时间、性别、年龄段、景点名、景点类型和统计口径；不要总是显式说“游客行为数据”。",
    "FUSION": "保留推荐意图、偏好人群、路线规划语义和灵山胜境场景。",
    "BOUNDARY": "保留不可回答或需拒答的风险点，不要把问题改成可直接回答的普通事实题。",
}


def load_cases(dataset_path: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    with open(dataset_path, "r", encoding="utf-8") as file_obj:
        for line_number, raw_line in enumerate(file_obj, start=1):
            line = raw_line.strip()
            if not line:
                continue
            case = json.loads(line)
            if "id" not in case or "query" not in case:
                raise ValueError(f"invalid case at line {line_number}: missing id/query")
            cases.append(case)
    return cases


def rewrite_unified_eval_cases(
    dataset_path: Path = DEFAULT_OUTPUT_PATH,
    output_path: Path = DEFAULT_REWRITTEN_OUTPUT_PATH,
    cache_path: Path = DEFAULT_REWRITE_CACHE_PATH,
    report_path: Optional[Path] = DEFAULT_REWRITE_REPORT_PATH,
    batch_size: int = 16,
    limit: Optional[int] = None,
    temperature: float = 0.75,
    max_retries: int = 3,
) -> Dict[str, Any]:
    if not llm_is_configured():
        raise RuntimeError("LLM is not configured. Please set LLM_API_KEY, LLM_API_BASE, and LLM_MODEL_NAME.")

    cases = load_cases(dataset_path)
    selected_ids = {case["id"] for case in cases[:limit]} if limit else {case["id"] for case in cases}
    cache = _load_cache(cache_path)
    rewritten: List[Dict[str, Any]] = []
    rewrite_failures: List[Dict[str, Any]] = []
    started_at = time.time()

    pending = [case for case in cases if case["id"] in selected_ids and case["id"] not in cache]
    for batch in _chunks(pending, batch_size):
        batch_result = _rewrite_batch_with_retries(
            batch=batch,
            temperature=temperature,
            max_retries=max_retries,
        )
        for case in batch:
            item = batch_result.get(case["id"])
            if item:
                cache[case["id"]] = item
                _append_cache_item(cache_path, item)
            else:
                rewrite_failures.append(
                    {
                        "id": case["id"],
                        "query": case["query"],
                        "reason": "missing rewrite in LLM response",
                    }
                )

    seen_queries: set[str] = set()
    duplicate_rewrites: List[Dict[str, Any]] = []
    fallback_count = 0
    changed_count = 0

    for index, case in enumerate(cases):
        next_case = dict(case)
        if next_case["id"] in selected_ids:
            rewrite = cache.get(next_case["id"])
            normalized_rewrite = _normalized_rewrite(case, rewrite) if rewrite else None
            validation_error = _validate_rewrite(case, normalized_rewrite, seen_queries) if normalized_rewrite else "no rewrite available"
            if validation_error == "duplicate query":
                normalized_rewrite = _dedupe_rewrite(case, normalized_rewrite, seen_queries)
                validation_error = _validate_rewrite(case, normalized_rewrite, seen_queries)
            if validation_error:
                fallback_count += 1
                rewrite_failures.append(
                    {
                        "id": case["id"],
                        "query": case["query"],
                        "reason": validation_error,
                    }
                )
                new_query = case["query"]
                style = "fallback_original"
                notes = validation_error
            else:
                new_query = str(normalized_rewrite["query"]).strip()
                style = str(normalized_rewrite.get("style") or _style_for_case(index))
                notes = str(normalized_rewrite.get("notes") or "")
                if new_query != case["query"]:
                    changed_count += 1
            next_case["query"] = new_query
            next_case["rewrite_of"] = case["query"]
            next_case["rewrite_style"] = style
            next_case["rewrite_notes"] = notes
            next_case["tags"] = _merge_tags(
                next_case.get("tags") or [],
                ["llm_rewrite", f"rewrite:{_slug_style(style)}"],
            )
        else:
            next_case["rewrite_of"] = ""
            next_case["rewrite_style"] = "unchanged"
            next_case["rewrite_notes"] = ""

        if next_case["query"] in seen_queries:
            duplicate_rewrites.append({"id": next_case["id"], "query": next_case["query"]})
        seen_queries.add(next_case["query"])
        rewritten.append(next_case)

    if duplicate_rewrites:
        raise ValueError(f"duplicate rewritten queries found: {duplicate_rewrites[:5]}")

    expected_counts = dict(Counter(case["gold_source"] for case in cases))
    expected_dev_counts = {
        source: sum(1 for case in cases if case["gold_source"] == source and case["suite"] == "dev")
        for source in expected_counts
    }
    validation = validate_cases(rewritten, expected_counts, expected_dev_counts)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_jsonl(rewritten), encoding="utf-8")

    report = {
        "ok": True,
        "dataset": str(dataset_path),
        "output": str(output_path),
        "cache": str(cache_path),
        "case_count": len(rewritten),
        "selected_count": len(selected_ids),
        "changed_count": changed_count,
        "fallback_count": fallback_count,
        "failure_count": len(rewrite_failures),
        "failures": rewrite_failures[:100],
        "by_gold_source": dict(Counter(case["gold_source"] for case in rewritten)),
        "by_rewrite_style": dict(Counter(case.get("rewrite_style", "") for case in rewritten)),
        "validation": validation,
        "elapsed_seconds": round(time.time() - started_at, 3),
    }

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _rewrite_batch_with_retries(
    batch: Sequence[Dict[str, Any]],
    temperature: float,
    max_retries: int,
) -> Dict[str, Dict[str, str]]:
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            return _rewrite_batch(batch, temperature=temperature)
        except Exception as exc:
            last_error = str(exc)
            if attempt < max_retries:
                time.sleep(min(2**attempt, 8))
    return {
        case["id"]: {
            "id": case["id"],
            "query": case["query"],
            "style": "fallback_original",
            "notes": f"LLM rewrite failed: {last_error}",
        }
        for case in batch
    }


def _rewrite_batch(batch: Sequence[Dict[str, Any]], temperature: float) -> Dict[str, Dict[str, str]]:
    client = get_llm_client()
    prompt = _build_prompt(batch)
    response = client.chat.completions.create(
        model=_model_name(),
        messages=[
            {
                "role": "system",
                "content": (
                    "你是中文评测数据集改写专家。你的任务是改写用户问题，保留评测标签和答案条件，"
                    "只输出严格 JSON，不要输出 Markdown。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max(2048, len(batch) * 180),
    )
    content = response.choices[0].message.content or ""
    payload = _parse_json_object(content)
    items = payload.get("rewrites")
    if not isinstance(items, list):
        raise ValueError("LLM response missing rewrites array")

    result: Dict[str, Dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("id") or "").strip()
        query = str(item.get("query") or "").strip()
        if not case_id or not query:
            continue
        result[case_id] = {
            "id": case_id,
            "query": query,
            "style": str(item.get("style") or "").strip(),
            "notes": str(item.get("notes") or "").strip(),
        }
    return result


def _model_name() -> str:
    from app.core.config import settings

    return settings.LLM_MODEL_NAME


def _build_prompt(batch: Sequence[Dict[str, Any]]) -> str:
    items = []
    for index, case in enumerate(batch):
        style = _style_for_case(index)
        items.append(
            {
                "id": case["id"],
                "category": case.get("category"),
                "style": style,
                "guidance": CATEGORY_GUIDANCE.get(str(case.get("category")), "保留原问题语义。"),
                "original_query": case["query"],
                "expected_intent": case.get("expected_intent"),
                "answer_type": case.get("answer_type"),
                "locked_terms": _locked_terms(case),
                "must_include_in_answer": case.get("must_include") or [],
                "must_not_include_in_answer": case.get("must_not_include") or [],
                "gold_sql": case.get("gold_sql") or "",
                "expected": case.get("expected") or {},
                "gold_summary": case.get("gold_summary") or "",
            }
        )
    return (
        "请把下面每条评测问题改写成更真实、多样的中文用户问法。\n"
        "硬性要求：\n"
        "1. 不能改变问题的可回答范围、统计口径、筛选条件、实体、时间、排序方向、TopN 数量或拒答风险。\n"
        "2. locked_terms 必须原样保留在改写后的 query 中。\n"
        "3. 不要把答案写进问题；不要添加原题没有的新事实或新限制。\n"
        "4. 行为分析题可以弱化“游客行为数据”这个字面提示，但不能改变为景区官方事实题。\n"
        "5. 边界题必须仍然是边界/拒答测试，不能改成可直接回答的问题。\n"
        "6. 每条 query 尽量和 original_query 句式不同，长度控制在 8 到 60 个中文字符左右。\n"
        "只输出 JSON 对象，格式为：{\"rewrites\":[{\"id\":\"...\",\"query\":\"...\",\"style\":\"...\",\"notes\":\"...\"}]}。\n\n"
        f"待改写样例：\n{json.dumps(items, ensure_ascii=False, indent=2)}"
    )


def _locked_terms(case: Dict[str, Any]) -> List[str]:
    terms: List[str] = []
    query = str(case.get("query") or "")
    core_query = _core_query(query)
    category = str(case.get("category") or "")
    gold_sql = str(case.get("gold_sql") or "")
    expected = case.get("expected") or {}

    if category in {"DOCX_STRUCTURED", "DOCX_RAG"}:
        terms.extend(_known_entities_in_text(query))
        if case.get("must_include"):
            terms.append(str(case["must_include"][0]))
    elif category == "BEHAVIOR_SQL":
        terms.extend(term for term in _sql_string_literals(gold_sql) if not term.isdigit())
        terms.extend(re.findall(r"\d{4}年|\d{1,2}月|\d{1,2}-\d{1,2}岁|60岁及以上|前\d+", query))
    elif category == "FUSION":
        if "灵山胜境" in query:
            terms.append("灵山胜境")
        for value in expected.get("route_contains", []):
            if value in query:
                terms.append(str(value))
    elif category == "BOUNDARY":
        terms.extend(_known_entities_in_text(core_query))
        terms.extend(re.findall(r"DOCX|U\d+|\d{4}年|今天|明天|当前|现在|下周|实时|手机号|真实姓名", core_query))

    return _unique([term for term in terms if term and term in query])


def _core_query(query: str) -> str:
    for delimiter in ("：", ":"):
        if delimiter in query:
            return query.rsplit(delimiter, 1)[-1].strip()
    return query


def _known_entities_in_text(text: str) -> List[str]:
    candidates = [
        "灵山胜境",
        "灵山大照壁",
        "灵山大佛",
        "灵山梵宫",
        "九龙灌浴",
        "祥符禅寺",
        "五印坛城",
        "小灵山庵",
        "小灵山",
        "登云道",
        "佛手广场",
        "上海迪士尼",
    ]
    return [candidate for candidate in candidates if candidate in text]


def _sql_string_literals(sql: str) -> List[str]:
    return [
        item.replace("''", "'")
        for item in re.findall(r"'((?:''|[^'])*)'", sql)
        if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", item)
    ]


def _validate_rewrite(case: Dict[str, Any], rewrite: Optional[Dict[str, str]], seen_queries: set[str]) -> str:
    if not rewrite:
        return "missing rewrite"
    query = str(rewrite.get("query") or "").strip()
    if not query:
        return "empty query"
    if query in seen_queries:
        return "duplicate query"
    if len(query) < 4:
        return "query too short"
    if len(query) > 90:
        return "query too long"
    missing_terms = [term for term in _locked_terms(case) if not _term_satisfied(term, query)]
    if missing_terms:
        return f"missing locked terms: {missing_terms[:5]}"
    return ""


def _normalized_rewrite(case: Dict[str, Any], rewrite: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    if not rewrite:
        return None
    query = str(rewrite.get("query") or "").strip()
    if not query:
        return dict(rewrite)

    locked_terms = _locked_terms(case)
    if "2025年" in locked_terms and "2025年" not in query:
        query = query.replace("今年", "2025年")
        if "2025年" not in query:
            month_match = re.search(r"(\d{1,2})\s*月", query)
            if month_match:
                query = query[: month_match.start()] + "2025年" + query[month_match.start() :]
            else:
                query = "2025年" + query

    replacements = [
        ("灵山胜境", "灵山"),
        ("上海迪士尼", "迪士尼"),
        ("灵山梵宫", "梵宫"),
    ]
    for required, alias in replacements:
        if required in locked_terms and required not in query and alias in query:
            query = query.replace(alias, required, 1)

    if "女" in locked_terms and "女" not in query:
        query = query.replace("她们", "女性游客", 1)
    if "男" in locked_terms and "男" not in query:
        query = query.replace("他们", "男性游客", 1)
    if "真实姓名" in locked_terms and "真实姓名" not in query and "姓名" in query:
        query = query.replace("姓名", "真实姓名", 1)
    if "今天" in locked_terms and "今天" not in query:
        query = query.replace("现在", "今天实时" if "实时" in locked_terms else "今天", 1)
        if "今天" not in query:
            query = "今天" + query
    if "实时" in locked_terms and "实时" not in query:
        if "有多少人" in query:
            query = query.replace("有多少人", "实时客流是多少", 1)
        elif "客流" in query:
            query = query.replace("客流", "实时客流", 1)
        else:
            query = "实时" + query

    next_rewrite = dict(rewrite)
    next_rewrite["query"] = query
    return next_rewrite


def _dedupe_rewrite(
    case: Dict[str, Any],
    rewrite: Optional[Dict[str, str]],
    seen_queries: set[str],
) -> Optional[Dict[str, str]]:
    if not rewrite:
        return rewrite
    original_query = str(case.get("query") or "")
    query = str(rewrite.get("query") or "").strip()
    candidates = []
    if "如果评委追问" in original_query and not query.startswith("如果评委追问"):
        candidates.append(f"如果评委追问：{query}")
    if str(case.get("category")) == "FUSION":
        candidates.extend(
            [
                query.rstrip("？?。") + "，重点亲子内容怎么安排？",
                query.rstrip("？?。") + "，按孩子兴趣怎么走？",
            ]
        )
    candidates.append(original_query)

    for candidate in candidates:
        if candidate and candidate not in seen_queries:
            next_rewrite = dict(rewrite)
            next_rewrite["query"] = candidate
            return next_rewrite
    return rewrite


def _term_satisfied(term: str, query: str) -> bool:
    if term in query:
        return True
    if term == "前5":
        return bool(re.search(r"前\s*(5|五)|top\s*5|哪\s*5|5\s*(个|类|项|种)|五\s*(个|类|项|种)", query, re.IGNORECASE))
    if term == "60岁及以上":
        return bool(re.search(r"60\s*岁\s*(及以上|以上|\+)|60\s*及以上", query))
    if term == "当前":
        return "现在" in query or "实时" in query
    if term == "女":
        return "女性" in query or "女游客" in query
    if term == "男":
        return "男性" in query or "男游客" in query or "男的" in query
    if term.upper() == "DOCX":
        return "docx" in query.lower() or "Word" in query or "文档" in query
    if term == "风景名胜与休闲度假":
        return "风景名胜" in query and "休闲度假" in query
    return False


def _parse_json_object(text: str) -> Dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM response is not a JSON object")
    return payload


def _render_jsonl(cases: Iterable[Dict[str, Any]]) -> str:
    lines = []
    for case in cases:
        ordered = {field: case.get(field) for field in REWRITTEN_CASE_FIELD_ORDER if field in case}
        for key, value in case.items():
            if key not in ordered:
                ordered[key] = value
        lines.append(json.dumps(ordered, ensure_ascii=False, separators=(",", ":")) + "\n")
    return "".join(lines)


def _load_cache(cache_path: Path) -> Dict[str, Dict[str, str]]:
    if not cache_path.exists():
        return {}
    cache: Dict[str, Dict[str, str]] = {}
    with open(cache_path, "r", encoding="utf-8") as file_obj:
        for raw_line in file_obj:
            line = raw_line.strip()
            if not line:
                continue
            item = json.loads(line)
            case_id = str(item.get("id") or "")
            if case_id:
                cache[case_id] = item
    return cache


def _append_cache_item(cache_path: Path, item: Dict[str, str]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "a", encoding="utf-8") as file_obj:
        file_obj.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")


def _chunks(items: Sequence[Dict[str, Any]], size: int) -> Iterable[Sequence[Dict[str, Any]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _style_for_case(index: int) -> str:
    return STYLE_CYCLE[index % len(STYLE_CYCLE)]


def _slug_style(style: str) -> str:
    mapping = {
        "口语化游客提问": "spoken",
        "评委追问": "judge_followup",
        "省略数据源的自然问法": "implicit_source",
        "带轻微上下文的追问": "context_followup",
        "更短的移动端问法": "mobile_short",
        "更正式的验收问法": "formal_acceptance",
        "fallback_original": "fallback_original",
    }
    return mapping.get(style, re.sub(r"[^A-Za-z0-9_]+", "_", style).strip("_") or "custom")


def _merge_tags(existing: Sequence[str], additions: Sequence[str]) -> List[str]:
    return _unique([str(tag) for tag in list(existing) + list(additions) if str(tag).strip()])


def _unique(items: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Rewrite unified eval cases with an LLM paraphrase layer.")
    parser.add_argument("--dataset", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--output", default=str(DEFAULT_REWRITTEN_OUTPUT_PATH))
    parser.add_argument("--cache", default=str(DEFAULT_REWRITE_CACHE_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REWRITE_REPORT_PATH))
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=0.75)
    args = parser.parse_args(argv)

    report = rewrite_unified_eval_cases(
        dataset_path=Path(args.dataset).resolve(),
        output_path=Path(args.output).resolve(),
        cache_path=Path(args.cache).resolve(),
        report_path=Path(args.report).resolve() if args.report else None,
        batch_size=args.batch_size,
        limit=args.limit,
        temperature=args.temperature,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
