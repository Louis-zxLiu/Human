import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from app.core.runtime import PROJECT_ROOT, merge_runtime_status
from app.rag.pipeline import ScenicRAGPipeline


QUESTIONS_PATH = PROJECT_ROOT / "tests" / "manual_eval_questions.json"


def load_questions() -> List[Dict[str, Any]]:
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def run_eval_suite() -> Dict[str, Any]:
    pipeline = ScenicRAGPipeline()
    questions = load_questions()
    stats = defaultdict(lambda: {"total": 0, "passed": 0, "route_mismatch": 0})
    failures = []

    for item in questions:
        result = pipeline.process_query(item["query"])
        answer = result["answer"]
        expected_intent = item["expected_intent"]
        expected_keywords = item.get("expected_keywords", [])

        passed = result["intent"] == expected_intent and all(keyword in answer for keyword in expected_keywords)
        stats[item["category"]]["total"] += 1
        if passed:
            stats[item["category"]]["passed"] += 1
        else:
            if result["intent"] != expected_intent:
                stats[item["category"]]["route_mismatch"] += 1
            failures.append(
                {
                    "category": item["category"],
                    "query": item["query"],
                    "expected_intent": expected_intent,
                    "actual_intent": result["intent"],
                    "expected_keywords": expected_keywords,
                    "answer_preview": answer[:160],
                }
            )

    summary = {
        category: {
            **category_stats,
            "accuracy": round((category_stats["passed"] / category_stats["total"] * 100), 1)
            if category_stats["total"]
            else 0.0,
        }
        for category, category_stats in stats.items()
    }
    payload = {"summary": summary, "failures": failures[:10]}
    merge_runtime_status({"last_eval": payload})
    return payload
