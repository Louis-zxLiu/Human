from functools import lru_cache

from openai import OpenAI

from app.core.config import settings


def llm_is_configured() -> bool:
    api_key = str(settings.LLM_API_KEY or "").strip()
    base_url = str(settings.LLM_API_BASE or "").strip()
    model_name = str(settings.LLM_MODEL_NAME or "").strip()
    return bool(api_key and api_key != "sk-placeholder" and base_url and model_name)


@lru_cache(maxsize=1)
def get_llm_client() -> OpenAI:
    """
    初始化并返回一个配置好环境参数的 OpenAI 客户端实例。
    兼容 DeepSeek 等支持 OpenAI 标准协议的模型。
    """
    return OpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE,
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
    """
    统一的 LLM 生成接口。

    在真实运行中，LLM 是增强器而不是单点依赖；当配置缺失或调用失败时，
    调用方可以选择接收错误文本，或拿到空字符串走确定性降级分支。
    """
    if not llm_is_configured():
        return "LLM 调用失败: 未配置可用的 LLM 客户端。" if return_error_text else ""

    try:
        request_payload = {
            "model": settings.LLM_MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            request_payload["response_format"] = {"type": "json_object"}

        response = get_llm_client().chat.completions.create(**request_payload)
        message = response.choices[0].message.content
        return message.strip() if isinstance(message, str) else ""
    except Exception as exc:
        return f"LLM 调用失败: {str(exc)}" if return_error_text else ""
