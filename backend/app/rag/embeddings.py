"""SiliconFlow bge-m3（OpenAI 兼容）。LLM 与 Embedding 分属不同供应商是常态，
所以单独一层抽象——和 llm/provider.py 对称。"""
from langchain_openai import OpenAIEmbeddings

from app.config import settings


def get_embedder() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        base_url=settings.siliconflow_base_url,
        api_key=settings.siliconflow_api_key,
        # 关键：跳过 OpenAI 专属的 tiktoken 分块逻辑（bge-m3 不是 OpenAI 模型）
        check_embedding_ctx_length=False,
    )