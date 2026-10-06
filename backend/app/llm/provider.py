"""LLM 工厂：一处注册，处处使用。切换/新增模型只改这里。

设计要点：所有供应商都走 OpenAI 兼容协议（model_provider="openai" +
自定义 base_url），所以增加一个新供应商 = 加一个字典条目。
这就是面试所说的"多模型抽象与路由能力"的最小实现。
"""
from functools import lru_cache

from langchain.chat_models import init_chat_model

from app.config import settings


def _registry() -> dict:
    """每次调用重新读 settings，方便测试时覆盖。"""
    return {
        "doubao": dict(
            model=settings.doubao_model,
            model_provider="openai",
            base_url=settings.doubao_base_url,
            api_key=settings.doubao_api_key,
        ),
        "deepseek": dict(
            model="deepseek-chat",
            model_provider="openai",
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
        ),
        "qwen": dict(
            model="qwen-plus",
            model_provider="openai",
            base_url=settings.qwen_base_url,
            api_key=settings.qwen_api_key,
        ),
        "gpt": dict(
            model="gpt-4o",
            model_provider="openai",
            api_key=settings.gpt_api_key,
        ),
    }


def get_llm(key: str | None = None):
    """返回一个 LangChain ChatModel 实例。

    key 为空时用 settings.model_provider，实现"全局默认模型"。
    """
    key = key or settings.model_provider
    if key not in (reg := _registry()):
        raise ValueError(f"未知模型: {key}，可选: {list(reg)}")
    cfg = reg[key]
    if not cfg.get("model"):
        raise ValueError(f"模型 {key} 未配置：请先在 backend/.env 中填写对应的 MODEL 与 API_KEY")
    return init_chat_model(**cfg, temperature=settings.temperature)