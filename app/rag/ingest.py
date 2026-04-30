import os
import json
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from app.core.config import settings, resolve_path
from app.rag.docx_parser import DocxParser
from langchain.text_splitter import RecursiveCharacterTextSplitter

# 自定义基于本地模型的 Embedding Function，符合 ChromaDB 的接口规范
class LocalEmbeddingFunction(chromadb.api.types.EmbeddingFunction):
    def __init__(self, model_path: str, device: str = "cpu", normalize: bool = True):
        # 初始化本地 sentence-transformers 模型
        self.model = SentenceTransformer(model_path, device=device)
        self.normalize = normalize

    def __call__(self, input: list[str]) -> list[list[float]]:
        # 批量生成 Embedding 向量
        embeddings = self.model.encode(input, normalize_embeddings=self.normalize)
        return embeddings.tolist()

class KnowledgeIngestor:
    """
    负责将各种格式的数据（Docx文本、Docx表格、JSON提取出的纯文本）
    经过合理的分块（Chunking）后，向量化并存入 ChromaDB 向量库。
    """
    def __init__(self, collection_name: str = "scenic_knowledge"):
        self.db_dir = resolve_path(settings.CHROMA_DB_DIR)
        self.kb_dir = resolve_path(settings.KNOWLEDGE_BASE_DIR)
        self.collection_name = collection_name
        
        # 确保目录存在
        os.makedirs(self.db_dir, exist_ok=True)
        
        # 初始化 ChromaDB 客户端
        self.client = chromadb.PersistentClient(path=self.db_dir, settings=Settings(anonymized_telemetry=False))
        
        # 初始化 Embedding 模型 (bge-large-zh-v1.5)
        # 注意: 比赛要求使用离线模型，所以我们使用本地路径加载
        model_path = resolve_path(settings.MODEL_EMBEDDING_PATH)
        print(f"[*] 正在加载 Embedding 模型: {model_path}")
        self.embedding_function = LocalEmbeddingFunction(
            model_path=model_path,
            device=settings.EMBEDDING_DEVICE,
            normalize=settings.EMBEDDING_NORMALIZE
        )
        
        # 获取或创建集合
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function
        )
        
        # 文本分块器（用于长段落）
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,       # 500
            chunk_overlap=settings.CHUNK_OVERLAP, # 50
            separators=["\n\n", "\n", "。", "！", "？", "，", " "]
        )

    def process_docx(self, file_path: str):
        """解析并切分 Docx 文件（支持表格保护）"""
        print(f"[*] 正在解析 Docx 文件: {os.path.basename(file_path)}")
        parser = DocxParser(file_path)
        raw_chunks = parser.parse()
        
        final_docs = []
        final_metadatas = []
        final_ids = []
        
        chunk_counter = 0
        for chunk in raw_chunks:
            content = chunk["content"]
            metadata = chunk["metadata"]
            
            # 如果是普通的段落文本且较长，走文本分块器
            if metadata["type"] == "text" and len(content) > settings.CHUNK_SIZE:
                splits = self.text_splitter.split_text(content)
                for split_text in splits:
                    chunk_counter += 1
                    final_docs.append(split_text)
                    final_metadatas.append(metadata.copy())
                    final_ids.append(f"{metadata['file_id']}_text_{chunk_counter}")
                    
            # 如果是表格，或者短文本，不分块（因为分块会破坏表格Markdown结构）
            else:
                chunk_counter += 1
                final_docs.append(content)
                final_metadatas.append(metadata.copy())
                final_ids.append(f"{metadata['file_id']}_{metadata['type']}_{chunk_counter}")
                
        # 批量 Upsert 入库
        if final_docs:
            print(f"    -> 提取了 {len(final_docs)} 个高质量 Chunk，正在向量化并存入 ChromaDB...")
            self.collection.upsert(
                documents=final_docs,
                metadatas=final_metadatas,
                ids=final_ids
            )
            print("    -> 入库完成！")
            
    def process_json(self, json_path: str):
        """解析并切分从 Excel 中提取出来的静态景点 JSON 文本"""
        print(f"[*] 正在解析 JSON 文件: {os.path.basename(json_path)}")
        with open(json_path, 'r', encoding='utf-8') as f:
            attractions = json.load(f)
            
        final_docs = []
        final_metadatas = []
        final_ids = []
        
        for idx, item in enumerate(attractions):
            name = item.get("attraction_name", "")
            type_ = item.get("attraction_type", "")
            content = item.get("attraction_content", "")
            
            # 拼接成语义完整的文本
            full_text = f"【景点名称】: {name}\n【景点类型】: {type_}\n【详细介绍】: {content}"
            
            # 由于可能很长，用滑动窗口分块
            splits = self.text_splitter.split_text(full_text)
            for i, split_text in enumerate(splits):
                final_docs.append(split_text)
                final_metadatas.append({
                    "file_id": "excel_extracted_json",
                    "source": "unique_attractions.json",
                    "attraction_name": name,
                    "type": "text"
                })
                final_ids.append(f"attraction_{idx}_chunk_{i}")
                
        if final_docs:
            print(f"    -> 提取了 {len(final_docs)} 个高质量 Chunk，正在向量化并存入 ChromaDB...")
            self.collection.upsert(
                documents=final_docs,
                metadatas=final_metadatas,
                ids=final_ids
            )
            print("    -> 入库完成！")

if __name__ == "__main__":
    # 执行全量知识库构建
    print("="*50)
    print("🚀 开始构建本地静态知识库 (ChromaDB)")
    print("="*50)
    
    ingestor = KnowledgeIngestor()
    
    # 1. 注入两个 Docx 知识库
    docx1 = os.path.join(settings.KNOWLEDGE_BASE_DIR, "灵山胜境 景点结构化数据集.docx")
    docx2 = os.path.join(settings.KNOWLEDGE_BASE_DIR, "灵山胜境：历史、文化、景点特色与个性化游览指南.docx")
    
    if os.path.exists(docx1):
        ingestor.process_docx(docx1)
    if os.path.exists(docx2):
        ingestor.process_docx(docx2)
        
    # 2. 注入刚才处理好的 Excel 静态 JSON 数据
    json_path = os.path.join(os.path.dirname(settings.KNOWLEDGE_BASE_DIR), "processed", "unique_attractions.json")
    if os.path.exists(json_path):
        ingestor.process_json(json_path)
        
    print("\n[+] 全量静态知识库入库完毕！")
