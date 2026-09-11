"""LLM provider factory."""

from config import LLMConfig
from src.providers.base import LLMProvider


def get_provider() -> LLMProvider:
    if LLMConfig.provider != "deepseek":
        raise ValueError(f"Unsupported LLM provider: {LLMConfig.provider}")
    from src.providers.deepseek import DeepSeekProvider

    return DeepSeekProvider.get_instance()


__all__ = ["LLMProvider", "get_provider"]
