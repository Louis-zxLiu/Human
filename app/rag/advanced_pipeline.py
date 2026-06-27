# DEPRECATED: This module has been superseded by the LangGraph pipeline.
# CrossEncoder reranking is now available in ChromaStaticAgent(use_reranker=True).
# This file is kept for reference only and is not imported anywhere in production.
import warnings
warnings.warn(
    "advanced_pipeline.py is deprecated. Use app.rag.chroma_agent.ChromaStaticAgent(use_reranker=True) instead.",
    DeprecationWarning,
    stacklevel=2,
)


# Initialize local embedding model wrapper for LangChain
class LocalEmbeddings:
    def __init__(self, model_name="shibing624/text2vec-base-chinese", device="cpu"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name, device=device)
        
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()
        
    def embed_query(self, text: str) -> List[float]:
        return self.model.encode([text], normalize_embeddings=True).tolist()[0]

class AdvancedScenicRAG:
    """
    高级 RAG 管道：
    1. 解析 docx/excel，智能切分表格 (提取 markdown 表格结构 + 附加上下文)
    2. 存入 ChromaDB
    3. EnsembleRetriever (BM25 + Chroma Vector Top-5)
    4. Cross-encoder rerank (阈值 0.72)
    5. OpenAI 格式生成
    """
    def __init__(self):
        self.db_dir = resolve_path(settings.CHROMA_DB_DIR)
        self.embeddings = LocalEmbeddings(
            model_name="shibing624/text2vec-base-chinese",
            device=settings.EMBEDDING_DEVICE
        )
        
        self.chroma_client = chromadb.PersistentClient(path=self.db_dir, settings=Settings(anonymized_telemetry=False))
        self.collection_name = "advanced_scenic_docs"
        
        self.vector_store = Chroma(
            client=self.chroma_client,
            collection_name=self.collection_name,
            embedding_function=self.embeddings,
        )
        
        # 交叉编码器，用于重排 (Rerank)
        # 假设使用一个轻量级的跨语种重排模型
        self.reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device=settings.EMBEDDING_DEVICE)
        self.bm25_retriever = None
        self.all_documents = [] # 缓存用于 BM25 初始化
        
    def ingest_directory(self, data_dir: str):
        """读取项目根目录下的 docx/excel 资料并建库"""
        data_dir = resolve_path(data_dir)
        docs = []
        for root, dirs, files in os.walk(data_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if file.endswith(".docx"):
                    docs.extend(load_docx_with_tables(file_path, chunk_size=300, overlap=50))
                elif file.endswith(".xlsx") or file.endswith(".xls"):
                    docs.extend(load_excel(file_path, chunk_size=300, overlap=50))
                    
        if docs:
            # 存入 Chroma
            self.vector_store.add_documents(docs)
            self.all_documents.extend(docs)
            # 初始化 BM25
            self.bm25_retriever = BM25Retriever.from_documents(self.all_documents)
            self.bm25_retriever.k = 5
            
    def retrieve_and_rerank(self, query: str, top_k: int = 3, threshold: float = 0.72) -> List[LangChainDocument]:
        """混合检索 + 交叉编码重排"""
        if not self.bm25_retriever:
            # 如果是从磁盘恢复，需要从 chroma 读取所有文本重新建立 bm25
            all_data = self.vector_store.get()
            docs = [LangChainDocument(page_content=t) for t in all_data['documents']]
            if docs:
                self.bm25_retriever = BM25Retriever.from_documents(docs)
                self.bm25_retriever.k = 5
            else:
                return []
                
        # Vector Retriever
        vector_retriever = self.vector_store.as_retriever(search_kwargs={"k": 5})
        
        # Ensemble (BM25 + Vector)
        ensemble_retriever = EnsembleRetriever(
            retrievers=[self.bm25_retriever, vector_retriever],
            weights=[0.5, 0.5]
        )
        
        # 初筛获取 Top N
        initial_docs = ensemble_retriever.get_relevant_documents(query)
        if not initial_docs:
            return []
            
        # Rerank
        pairs = [[query, doc.page_content] for doc in initial_docs]
        scores = self.reranker.predict(pairs)
        
        # 过滤与排序
        scored_docs = list(zip(initial_docs, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        
        # 根据阈值拦截
        final_docs = [doc for doc, score in scored_docs if score >= threshold]
        
        return final_docs[:top_k]

    def query(self, user_query: str) -> str:
        """端到端生成回答"""
        docs = self.retrieve_and_rerank(user_query, top_k=3, threshold=0.72)
        
        if not docs:
            return "抱歉，知识库中未找到相关内容，请重新描述您的问题。"
            
        context = "\n---\n".join([doc.page_content for doc in docs])
        
        sys_prompt = "你是一个专业的景区导览数字人。请基于以下参考资料，简明扼要地回答用户问题。严格按照资料中的数据（特别是表格中的数据）回答，不随意捏造。"
        prompt = f"参考资料：\n{context}\n\n用户提问: {user_query}\n回答："
        
        # 调用 SoulX-FlashHead-Lite-1.3B，最大 1000 tokens，temp 0.3
        return generate_chat_completion(prompt, sys_prompt, temperature=0.3, max_tokens=1000)

advanced_rag = AdvancedScenicRAG()
