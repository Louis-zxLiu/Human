import os
import chromadb
from chromadb.config import Settings
from app.core.config import settings, resolve_path
from app.rag.llm_client import generate_chat_completion

class ChromaStaticAgent:
    """
    处理纯文本和非结构化数据（历史故事/导览词）的 RAG Agent。
    利用本地 ChromaDB 和 Embedding 模型实现基于语义的相似度召回，并附带防止幻觉的硬拦截机制。
    """
    
    def __init__(self, collection_name: str = "scenic_knowledge"):
        self.db_dir = resolve_path(settings.CHROMA_DB_DIR)
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(path=self.db_dir, settings=Settings(anonymized_telemetry=False))
        
        model_path = resolve_path(settings.MODEL_EMBEDDING_PATH)
            
        # 初始化本地 sentence-transformers 模型
        self.embedding_function = chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_path,
            device=settings.EMBEDDING_DEVICE,
            normalize_embeddings=settings.EMBEDDING_NORMALIZE
        )
        
        # 尝试获取集合，如果不存在则捕获异常
        try:
            self.collection = self.client.get_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function
            )
        except Exception:
            self.collection = None

    def query(self, user_query: str, top_k: int = 3, threshold: float = 0.70) -> str:
        """主入口：执行向量检索并生成安全、不胡编乱造的回答"""
        
        if not self.collection:
            return "对不起，景区知识库（ChromaDB）暂未初始化或无数据，请联系管理员先上传资料。"
            
        # 1. 向量化提问并检索 (使用 bge-large-zh-v1.5)
        results = self.collection.query(
            query_texts=[user_query],
            n_results=top_k
        )
        
        documents = [doc for doc in results.get("documents", [[]])[0] if doc]
        distances = results.get("distances", [[]])[0] # L2 距离，越小越相似
        
        # 2. 硬拦截机制：如果距离太大 (相似度低于阈值)，直接拦截，防止幻觉
        # 假设距离阈值为 1.2 (L2 distance)，如果全部大于 1.2，说明找不到相关内容
        # 这里仅作逻辑示意，具体阈值需依据你的 Embedding 模型进行调整。
        if not distances or all(d > 1.2 for d in distances):
            return "抱歉，您问的这个问题目前景区的知识库中暂未收录相关信息，建议您可以去服务台咨询。"
            
        # 3. 构建 Prompt 并生成回答
        if not documents:
            return "抱歉，您问的这个问题目前景区的知识库中暂未收录相关信息，建议您可以去服务台咨询。"

        context = "\n".join(documents)
        sys_prompt = "你是一个专业的景区导览数字人。请**仅根据**以下参考资料回答问题。如果参考资料中没有相关信息，请直接回答‘我暂时不了解这部分信息’，严禁自己编造。请绝对不要输出任何表情符号，因为回答会被直接用于语音播报。"
        prompt = f"""
参考资料：
{context}

用户提问: "{user_query}"

请用自然、亲切的导游语气回答：
"""
        final_answer = generate_chat_completion(prompt, sys_prompt, temperature=0.1)
        if final_answer.startswith("LLM 调用失败"):
            fallback = context.replace("\n", " ").strip()
            return f"根据景区资料，{fallback[:220]}" + ("..." if len(fallback) > 220 else "")
        return final_answer
