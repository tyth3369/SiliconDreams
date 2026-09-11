"""Provider-neutral language-model interface used by the application."""

from __future__ import annotations

from collections.abc import Generator
from typing import Protocol


class LLMProvider(Protocol):
    model: str
    reasoner_model: str

    def chat(self, messages: list[dict], **kwargs) -> str: ...

    def chat_stream(self, messages: list[dict], **kwargs) -> Generator[str, None, None]: ...

    def chat_with_tools(self, messages: list[dict], tools: list[dict], **kwargs) -> dict: ...
