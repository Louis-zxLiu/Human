from openai import OpenAI
from app.core.config import settings

def get_llm_client():
    """
    初始化并返回一个配置好环境参数的 OpenAI 客户端实例。
    兼容 DeepSeek 等支持 OpenAI 标准协议的模型。
    """
    client = OpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE
    )
    return client

def generate_chat_completion(prompt: str, system_prompt: str = "你是一个有用的AI助手。", temperature: float = 0.3) -> str:
    """
    统一的 LLM 生成接口
    """
    client = get_llm_client()
    try:
        response = client.chat.completions.create(
            model=settings.LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_tokens=1024
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"LLM 调用失败: {str(e)}"
