from functools import lru_cache
from typing import Optional

from app.core.config import settings


def llm_is_configured() -> bool:
    api_key = str(settings.LLM_API_KEY or "").strip()
    base_url = str(settings.LLM_API_BASE or "").strip()
    model_name = str(settings.LLM_MODEL_NAME or "").strip()
    return bool(api_key and api_key != "sk-placeholder" and base_url and model_name)


@lru_cache(maxsize=1)
def get_chat_llm():
    """返回 LangChain ChatOpenAI 实例，兼容 DeepSeek 等 OpenAI 协议模型。"""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE,
        model=settings.LLM_MODEL_NAME,
        temperature=0.0,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
    )


def generate_chat_completion(
    prompt: str,
    system_prompt: str = "你是一个有用的AI助手。",
    temperature: float = 0.3,
    max_tokens: int = 1024,
    return_error_text: bool = True,
    json_mode: bool = False,
) -> str:
    """统一 LLM 生成接口，内部使用 ChatOpenAI，保持原有签名不变。"""
    if not llm_is_configured():
        return "LLM 调用失败: 未配置可用的 LLM 客户端。" if return_error_text else ""

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = get_chat_llm()
        # 按调用参数动态调整 temperature / max_tokens
        bound = llm.bind(temperature=temperature, max_tokens=max_tokens)
        if json_mode:
            bound = bound.bind(response_format={"type": "json_object"})
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ]
        result = bound.invoke(messages)
        content = result.content if hasattr(result, "content") else str(result)
        return content.strip() if isinstance(content, str) else ""
    except Exception as exc:
        return f"LLM 调用失败: {str(exc)}" if return_error_text else ""
