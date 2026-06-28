from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from app.core.config import bocha_is_configured, settings
from app.rag.llm_client import generate_chat_completion, llm_is_configured
from app.rag.response_contract import make_evidence


class BochaSearchAgent:
    """Web search agent backed by the Bocha AI search API."""

    def search(self, query: str, *, search_query: Optional[str] = None) -> Dict[str, Any]:
        if not bocha_is_configured():
            return self._refused("博查 API 未配置，无法执行联网搜索。")

        effective_query = str(search_query or query or "").strip()
        if not effective_query:
            return self._refused("搜索词为空。")

        try:
            web_results = self._call_bocha_api(effective_query)
        except Exception as exc:
            return self._refused(f"联网搜索请求失败：{exc}", warnings=[f"bocha_api_error:{exc}"])

        pages = web_results.get("webPages", {}).get("value") or []
        if not pages:
            return {
                "answer": "联网搜索未返回相关结果。",
                "response_kind": "web_search_empty",
                "evidence": [],
                "trace": {"query": effective_query, "results_count": 0},
                "warnings": [],
                "refusal": None,
            }

        evidence = self._build_evidence(pages)
        snippets = self._build_snippets(pages)

        if llm_is_configured():
            answer = self._synthesize(query, snippets)
            response_kind = "web_search_answer"
        else:
            answer = snippets
            response_kind = "web_search_fallback"

        return {
            "answer": answer,
            "response_kind": response_kind,
            "evidence": evidence,
            "trace": {
                "query": effective_query,
                "results_count": len(pages),
                "llm_synthesized": llm_is_configured(),
            },
            "warnings": [],
            "refusal": None,
        }

    def _call_bocha_api(self, query: str) -> Dict[str, Any]:
        url = f"{settings.BOCHA_API_BASE.rstrip('/')}/web-search"
        payload = json.dumps({
            "query": query,
            "freshness": settings.BOCHA_SEARCH_FRESHNESS,
            "summary": True,
            "count": settings.BOCHA_SEARCH_COUNT,
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.BOCHA_API_KEY}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        # API wraps results under "data" key
        return payload.get("data") or payload

    def _build_evidence(self, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        evidence = []
        for page in pages[:settings.BOCHA_SEARCH_COUNT]:
            snippet = str(page.get("summary") or page.get("snippet") or "")[:240]
            if not snippet:
                continue
            evidence.append(make_evidence(
                "web_search",
                str(page.get("name") or page.get("url") or "web_result"),
                entity=None,
                field="web_snippet",
                snippet=snippet,
                score=round(float(page.get("score") or 0.8), 4),
                metadata={"url": str(page.get("url") or "")},
            ))
        return evidence

    def _build_snippets(self, pages: List[Dict[str, Any]]) -> str:
        parts = []
        for i, page in enumerate(pages[:settings.BOCHA_SEARCH_COUNT], 1):
            title = str(page.get("name") or "")
            snippet = str(page.get("summary") or page.get("snippet") or "")
            if snippet:
                parts.append(f"{i}. 【{title}】{snippet}")
        return "\n".join(parts)

    def _synthesize(self, user_query: str, snippets: str) -> str:
        system_prompt = (
            "你是景区数字人导游，直接用第一人称自然地回答游客问题。"
            "禁止用搜索结果开场，直接给出答案。"
            "只使用搜索到的信息，不要编造内容，语气亲切自然，适合口播。"
        )
        prompt = (
            f"用户问题：{user_query}\n\n"
            f"网络搜索结果：\n{snippets}\n\n"
            "请综合以上信息，给出简洁准确的回答。"
        )
        result = generate_chat_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.1,
            max_tokens=512,
            return_error_text=False,
        )
        return str(result or snippets)

    @staticmethod
    def _refused(message: str, *, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
        return {
            "answer": message,
            "response_kind": "refused:web_search_unavailable",
            "evidence": [],
            "trace": {},
            "warnings": warnings or [],
            "refusal": {
                "reason": "web_search_unavailable",
                "message": message,
                "suggested_queries": [],
            },
        }
