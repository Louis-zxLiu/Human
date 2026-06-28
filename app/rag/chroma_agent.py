from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings

from app.core.config import resolve_path, settings
from app.rag.llm_client import generate_chat_completion
from app.rag.response_contract import make_evidence


TOKEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")


@dataclass
class RetrievedChunk:
    text: str
    metadata: Dict[str, Any]
    dense_score: float
    lexical_score: float
    contextual_score: float

    @property
    def score(self) -> float:
        return self.dense_score + self.lexical_score + self.contextual_score


class ChromaStaticAgent:
    """
    Hybrid scenic retriever for non-structured scenic knowledge.

    Real-world behavior:
    - keep structured facts and SQL outside of RAG
    - use dense retrieval from Chroma as the primary recall path
    - blend in lexical and context bonuses for better precision on scenic docs
    - optionally rerank with CrossEncoder (use_reranker=True, threshold 0.72)
    - degrade gracefully to deterministic evidence snippets when LLM is absent
    """

    RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    RERANKER_THRESHOLD = 0.72

    def __init__(self, collection_name: str = "scenic_knowledge", use_reranker: bool = False):
        self.db_dir = resolve_path(settings.CHROMA_DB_DIR)
        self.collection_name = collection_name
        self.use_reranker = use_reranker
        self._reranker = None  # lazy-loaded on first use
        self.client = chromadb.PersistentClient(
            path=self.db_dir,
            settings=Settings(anonymized_telemetry=False),
        )

        model_path = resolve_path(settings.MODEL_EMBEDDING_PATH)
        self.embedding_function = chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_path,
            device=settings.EMBEDDING_DEVICE,
            normalize_embeddings=settings.EMBEDDING_NORMALIZE,
        )
        try:
            self.collection = self.client.get_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function,
            )
        except Exception:
            self.collection = None

    def query(self, user_query: str, top_k: int = 4, threshold: float = 0.78) -> str:
        return self.query_with_trace(user_query, top_k=top_k, threshold=threshold)["answer"]

    def query_with_trace(self, user_query: str, top_k: int = 4, threshold: float = 0.78) -> Dict[str, Any]:
        if not self.collection:
            return {
                "answer": "对不起，景区知识库暂未初始化或无数据，请联系管理员先上传资料。",
                "response_kind": "refused:kb_unavailable",
                "evidence": [],
                "trace": {"retrieval_mode": "unavailable", "llm_used": False},
            }

        chunks = self._hybrid_retrieve(user_query, top_k=top_k)
        if not chunks:
            return {
                "answer": "抱歉，您问的这个问题目前景区的知识库中暂未收录相关信息，建议您可以去服务台咨询。",
                "response_kind": "refused:no_relevant_docs",
                "evidence": [],
                "trace": {"retrieval_mode": "hybrid", "llm_used": False, "top_k": top_k},
            }

        best_score = chunks[0].score
        evidence = [self._chunk_evidence(chunk) for chunk in chunks[:top_k]]
        if best_score < threshold:
            return {
                "answer": "抱歉，您问的这个问题目前景区的知识库中暂未收录相关信息，建议您可以去服务台咨询。",
                "response_kind": "refused:low_confidence",
                "evidence": evidence[:2],
                "trace": {
                    "retrieval_mode": "hybrid",
                    "llm_used": False,
                    "top_k": top_k,
                    "best_score": round(best_score, 4),
                },
            }

        context = self._build_context(chunks)
        sys_prompt = (
            "你是景区的数字人导游，直接用第一人称自然地回答游客问题。"
            "禁止用'根据现有资料'、'根据资料' 等开场白——直接给出答案。"
            "如果资料确实不足，简短说明即可，不要编造。"
            "语气亲切自然，适合口播，不要输出表情或符号。"
        )
        prompt = f"参考资料：\n{context}\n\n游客提问：{user_query}\n\n请直接回答："
        final_answer = generate_chat_completion(
            prompt,
            sys_prompt,
            temperature=0.1,
            max_tokens=220,
            return_error_text=False,
        )
        if final_answer:
            return {
                "answer": final_answer,
                "response_kind": "rag_answer",
                "evidence": evidence,
                "trace": {
                    "retrieval_mode": "hybrid",
                    "llm_used": True,
                    "top_k": top_k,
                    "best_score": round(best_score, 4),
                },
            }
        return {
            "answer": self._render_evidence_fallback(chunks),
            "response_kind": "rag_fallback",
            "evidence": evidence,
            "trace": {
                "retrieval_mode": "hybrid",
                "llm_used": False,
                "top_k": top_k,
                "best_score": round(best_score, 4),
            },
        }

    def _hybrid_retrieve(self, user_query: str, top_k: int = 4) -> List[RetrievedChunk]:
        dense_results = self.collection.query(query_texts=[user_query], n_results=10)
        dense_documents = dense_results.get("documents", [[]])[0]
        dense_metadatas = dense_results.get("metadatas", [[]])[0]
        dense_distances = dense_results.get("distances", [[]])[0]
        if not dense_documents:
            return []

        query_tokens = self._tokens(user_query)
        scenic_terms = [token for token in query_tokens if token in {"灵山", "灵山胜境", "拈花湾", "禅意小镇"}]
        ranked: List[RetrievedChunk] = []
        for doc_text, metadata, distance in zip(dense_documents, dense_metadatas, dense_distances):
            dense_score = self._distance_to_score(distance)
            lexical_score = self._lexical_overlap(query_tokens, self._tokens(doc_text))
            contextual_score = self._context_bonus(doc_text, scenic_terms)
            ranked.append(
                RetrievedChunk(
                    text=doc_text,
                    metadata=metadata or {},
                    dense_score=dense_score,
                    lexical_score=lexical_score,
                    contextual_score=contextual_score,
                )
            )

        ranked.sort(key=lambda item: item.score, reverse=True)

        if self.use_reranker and ranked:
            ranked = self._rerank(user_query, ranked)

        return ranked[:top_k]

    def _rerank(self, query: str, chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder
                self._reranker = CrossEncoder(self.RERANKER_MODEL, device=settings.EMBEDDING_DEVICE)
            except Exception:
                return chunks
        try:
            pairs = [[query, chunk.text] for chunk in chunks]
            scores = self._reranker.predict(pairs)
            scored = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
            return [chunk for chunk, score in scored if score >= self.RERANKER_THRESHOLD]
        except Exception:
            return chunks

    @staticmethod
    def _distance_to_score(distance: Any) -> float:
        try:
            numeric = float(distance)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, 1.4 - numeric)

    @staticmethod
    def _tokens(text: str) -> List[str]:
        return [token.lower() for token in TOKEN_RE.findall(str(text or ""))]

    @staticmethod
    def _lexical_overlap(query_tokens: List[str], doc_tokens: List[str]) -> float:
        if not query_tokens or not doc_tokens:
            return 0.0
        doc_set = set(doc_tokens)
        overlap = sum(1 for token in query_tokens if token in doc_set)
        return min(0.8, overlap / max(len(set(query_tokens)), 1))

    @staticmethod
    def _context_bonus(doc_text: str, scenic_terms: List[str]) -> float:
        if not scenic_terms:
            return 0.0
        lowered = str(doc_text or "").lower()
        hits = sum(1 for term in scenic_terms if term.lower() in lowered)
        return min(0.25, hits * 0.08)

    @staticmethod
    def _build_context(chunks: List[RetrievedChunk]) -> str:
        sections = []
        for index, chunk in enumerate(chunks, start=1):
            source = str(chunk.metadata.get("source") or "")
            source_name = source.split("\\")[-1].split("/")[-1] if source else "知识资料"
            sections.append(f"[证据{index} | {source_name}]\n{chunk.text}")
        return "\n\n".join(sections)

    @staticmethod
    def _chunk_evidence(chunk: RetrievedChunk) -> Dict[str, Any]:
        source = str(chunk.metadata.get("source") or "")
        source_name = source.split("\\")[-1].split("/")[-1] if source else "knowledge_base"
        return make_evidence(
            "vector_doc",
            source_name,
            snippet=chunk.text,
            score=chunk.score,
            metadata={
                "dense_score": round(chunk.dense_score, 4),
                "lexical_score": round(chunk.lexical_score, 4),
                "contextual_score": round(chunk.contextual_score, 4),
            },
        )

    @staticmethod
    def _render_evidence_fallback(chunks: List[RetrievedChunk]) -> str:
        evidence_lines = []
        for chunk in chunks[:2]:
            cleaned = re.sub(r"\s+", " ", chunk.text).strip()
            if not cleaned:
                continue
            evidence_lines.append(cleaned[:180] + ("..." if len(cleaned) > 180 else ""))
        if not evidence_lines:
            return "抱歉，我暂时不了解这部分信息。"
        if len(evidence_lines) == 1:
            return f"根据景区资料，{evidence_lines[0]}"
        return f"根据景区资料，{evidence_lines[0]} 另外，{evidence_lines[1]}"
