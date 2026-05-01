import os
import torch

from app.core.chroma_telemetry import disable_chroma_telemetry
disable_chroma_telemetry()

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from app.core.config import settings, resolve_path
from app.rag.document_loader import load_docx_with_tables, load_excel

def init_knowledge_base():
    """
    Build the scenic knowledge base only from local scenic documents.
    The competition behavior-analysis Excel must not be ingested here.
    Supports incremental update and deletion.
    """
    # Use relative paths as per project rules
    docs_dir = resolve_path(settings.KNOWLEDGE_BASE_DIR)
    db_dir = resolve_path(settings.CHROMA_DB_DIR)

    if not os.path.exists(docs_dir):
        os.makedirs(docs_dir)
        print(f"[RAG] Created docs directory at {docs_dir}. Please add .docx or .xlsx files.")
        return

    # 1. Initialize Embeddings
    model_kwargs = {
        "device": settings.EMBEDDING_DEVICE
        if settings.EMBEDDING_DEVICE in {"cpu", "cuda"}
        else ("cuda" if torch.cuda.is_available() else "cpu")
    }
    embeddings = HuggingFaceBgeEmbeddings(
        model_name=resolve_path(settings.MODEL_EMBEDDING_PATH),
        model_kwargs=model_kwargs,
        encode_kwargs={"normalize_embeddings": settings.EMBEDDING_NORMALIZE},
        query_instruction=settings.EMBEDDING_QUERY_INSTRUCTION,
    )

    # 2. Load existing Chroma DB
    vectordb = Chroma(
        persist_directory=db_dir, 
        embedding_function=embeddings,
        collection_name="scenic_knowledge"
    )
    existing_data = vectordb.get()
    
    existing_ids = existing_data.get('ids', [])
    existing_metadatas = existing_data.get('metadatas', [])

    # Group existing IDs and track mtime by source
    source_to_ids = {}
    source_to_mtime = {}

    for doc_id, meta in zip(existing_ids, existing_metadatas):
        if not meta:
            continue
        source = meta.get('source')
        if not source:
            continue
        # Normalize source path for comparison
        source = os.path.normpath(source)
        if source not in source_to_ids:
            source_to_ids[source] = []
        source_to_ids[source].append(doc_id)
        
        # We assume all chunks of the same file have the same mtime
        mtime = meta.get('mtime')
        if mtime:
            source_to_mtime[source] = str(mtime)

    # 3. Scan directory and determine what needs to be added, updated, or deleted
    current_files = {}
    print(f"[RAG] Scanning directory: {docs_dir}")
    for file in os.listdir(docs_dir):
        if file.endswith('.docx') or file.endswith('.xlsx'):
            file_path = os.path.normpath(os.path.join(docs_dir, file))
            current_files[file_path] = str(os.path.getmtime(file_path))

    ids_to_delete = []
    files_to_process = []

    # Check for deleted or modified files
    for source, ids in source_to_ids.items():
        if source not in current_files:
            # File deleted
            print(f"[RAG] File deleted: {source}, removing from DB.")
            ids_to_delete.extend(ids)
        elif source_to_mtime.get(source) != current_files[source]:
            # File modified or missing mtime in DB
            print(f"[RAG] File modified or needs update: {source}, removing old chunks.")
            ids_to_delete.extend(ids)
            files_to_process.append(source)

    # Check for new files
    for source, mtime in current_files.items():
        if source not in source_to_ids:
            print(f"[RAG] New file detected: {source}")
            files_to_process.append(source)

    # 4. Perform Deletions
    if ids_to_delete:
        print(f"[RAG] Deleting {len(ids_to_delete)} stale chunks from DB...")
        # Delete in batches to avoid URI too long errors in some SQLite versions
        batch_size = 100
        for i in range(0, len(ids_to_delete), batch_size):
            vectordb.delete(ids=ids_to_delete[i:i+batch_size])

    # 5. Process new/modified files
    documents = []
    for file_path in files_to_process:
        try:
            mtime = current_files[file_path]
            if file_path.endswith('.docx'):
                print(f"[RAG] Parsing DOCX: {file_path}")
                docs = load_docx_with_tables(file_path, chunk_size=settings.CHUNK_SIZE, overlap=settings.CHUNK_OVERLAP)
                for doc in docs:
                    doc.metadata['mtime'] = mtime
                    doc.metadata['source'] = file_path
                documents.extend(docs)
            elif file_path.endswith('.xlsx'):
                print(f"[RAG] Parsing EXCEL: {file_path}")
                docs = load_excel(file_path, chunk_size=settings.CHUNK_SIZE, overlap=settings.CHUNK_OVERLAP)
                for doc in docs:
                    doc.metadata['mtime'] = mtime
                    doc.metadata['source'] = file_path
                documents.extend(docs)
        except Exception as e:
            print(f"[RAG] Error parsing {file_path}: {e}")

    if not documents:
        if ids_to_delete:
            if hasattr(vectordb, 'persist'):
                vectordb.persist()
            print("[RAG] Incremental update finished (deletions only).")
        else:
            print("[RAG] Knowledge base is up to date. No changes made.")
        return

    # Intelligent document parsing and chunking
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", "。", "！", "？", " ", ""]
    )
    chunks = text_splitter.split_documents(documents)
    print(f"[RAG] Split into {len(chunks)} new chunks.")

    # Add new chunks to DB
    print(f"[RAG] Adding new chunks to vector database at {db_dir}...")
    vectordb.add_documents(chunks)
    
    # Persist explicitly for older versions of chromadb if needed
    if hasattr(vectordb, 'persist'):
        vectordb.persist()
        
    print(f"[RAG] Successfully updated Chroma DB incrementally. Added {len(chunks)} chunks.")

if __name__ == "__main__":
    init_knowledge_base()
