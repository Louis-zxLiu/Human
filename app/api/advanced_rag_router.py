from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
import time

router = APIRouter(prefix="/v1", tags=["OpenAI Compatible RAG API"])

# 延迟初始化全局 RAG Pipeline 实例，防止在模块导入阶段和主线程发生 ChromaDB 抢占
rag_pipeline = None

def get_rag_pipeline():
    global rag_pipeline
    if rag_pipeline is None:
        from app.rag.pipeline import ScenicRAGPipeline
        rag_pipeline = ScenicRAGPipeline()
    return rag_pipeline

class Message(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = "SoulX-FlashHead-Lite-1.3B"
    messages: List[Message]
    temperature: float = 0.3
    max_tokens: int = 1024
    stream: Optional[bool] = False

@router.post("/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    OpenAI 兼容的 /v1/chat/completions 接口。
    前端（如数字人客户端）通过标准协议发送历史消息，
    后端截取最后一条用户提问，送入双轨制 RAG Pipeline (Router -> SQL/Chroma)，
    最后返回组装好的标准 JSON 响应。
    """
    user_query = ""
    # 从后往前找，找到最新的一条用户提问
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_query = msg.content
            break
            
    if not user_query:
        return {"error": "No user message found in the request."}
        
    conversation_context = [
        {"role": msg.role, "content": msg.content[:260], "meta": None}
        for msg in request.messages[-8:]
        if msg.content
    ]

    # 调用 Pipeline 核心入口，保留最近消息给主对话 Agent 做多轮决策。
    rag_pipeline = get_rag_pipeline()
    result = rag_pipeline.process_query(user_query, conversation_context=conversation_context)
    final_answer = result["answer"]
    rag_metadata = {
        "intent": result["intent"],
        "agent_type": result["agent_type"],
        "response_kind": result.get("response_kind"),
        "plan": result.get("plan"),
        "evidence": result.get("evidence", []),
        "refusal": result.get("refusal"),
        "warnings": result.get("warnings", []),
        "observability": result.get("observability"),
        "matched_attraction": result.get("matched_attraction"),
        "recommendation_label": result.get("recommendation_label"),
        "recommendation": result.get("recommendation"),
    }
    
    # 构造 OpenAI 标准的响应体
    return {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": final_answer,
                "metadata": rag_metadata,
            },
            "finish_reason": "stop"
        }],
        # 将 RAG 的调试信息塞进扩展字段，方便管理大屏或测试脚本查看
        "rag_metadata": rag_metadata,
        "usage": {
            "prompt_tokens": len(user_query),
            "completion_tokens": len(final_answer),
            "total_tokens": len(user_query) + len(final_answer)
        }
    }
