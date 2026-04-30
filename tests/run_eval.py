import json
import os
import sys
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.rag.pipeline import ScenicRAGPipeline


def load_questions() -> list[dict]:
    path = os.path.join(os.path.dirname(__file__), "manual_eval_questions.json")
    with open(path, "r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def main() -> None:
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

    print("=== Evaluation Summary ===")
    for category, category_stats in stats.items():
        total = category_stats["total"]
        passed = category_stats["passed"]
        ratio = (passed / total * 100) if total else 0
        print(
            f"{category}: {passed}/{total} passed | "
            f"accuracy={ratio:.1f}% | route_mismatch={category_stats['route_mismatch']}"
        )

    print("\n=== Failure Samples ===")
    for sample in failures[:10]:
        print(json.dumps(sample, ensure_ascii=False))


if __name__ == "__main__":
    main()
