"""Backward-compatible application facade for the configured LLM provider."""

from __future__ import annotations

from src.providers import get_provider
from src.providers.deepseek import DeepSeekProvider

# Preserve the public import used by existing integrations while moving the
# implementation behind the provider abstraction.
DeepSeekClient = DeepSeekProvider


def get_llm():
    return get_provider()


def llm_available() -> bool:
    return DeepSeekProvider.is_available()


__all__ = ["DeepSeekClient", "get_llm", "llm_available"]
