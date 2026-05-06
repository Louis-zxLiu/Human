import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.rag.pipeline import ScenicRAGPipeline

router = APIRouter()

_pipeline_cache: Optional[ScenicRAGPipeline] = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="scenic-guide")
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.3
    stream: Optional[bool] = False


class ChatCompletionResponseChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionResponseChoice]


def get_pipeline() -> ScenicRAGPipeline:
    global _pipeline_cache
    if _pipeline_cache is None:
        _pipeline_cache = ScenicRAGPipeline()
    return _pipeline_cache


def clear_runtime_cache() -> None:
    global _pipeline_cache
    _pipeline_cache = None


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest):
    user_message = next((msg.content for msg in reversed(request.messages) if msg.role == "user"), None)
    if not user_message:
        raise HTTPException(status_code=400, detail="No user message found in the request.")

    result = get_pipeline().process_query(user_message)
    answer = result["answer"]

    return ChatCompletionResponse(
        id=f"chatcmpl-{int(time.time())}",
        created=int(time.time()),
        model=request.model,
        choices=[
            ChatCompletionResponseChoice(
                index=0,
                message=ChatMessage(role="assistant", content=answer),
                finish_reason="stop",
            )
        ],
    )
