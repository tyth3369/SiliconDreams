"""DeepSeek V4 implementation of the provider-neutral LLM interface."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Generator
from typing import Any, ClassVar

from openai import OpenAI

from config import LLMConfig

logger = logging.getLogger(__name__)


def _usage_dict(usage: Any) -> dict[str, int]:
    """Normalize SDK usage objects without retaining request or response content."""
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        payload = usage.model_dump()
    elif isinstance(usage, dict):
        payload = usage
    else:
        payload = {
            key: getattr(usage, key, 0)
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "prompt_cache_hit_tokens",
                "prompt_cache_miss_tokens",
            )
        }
    return {
        key: max(0, int(payload.get(key) or 0))
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        )
    }


class DeepSeekProvider:
    _instance: ClassVar[DeepSeekProvider | None] = None
    supports_usage_callback: ClassVar[bool] = True

    def __init__(self) -> None:
        if not self.is_available():
            raise ValueError("DeepSeek API key is not configured in .env")
        self._client = OpenAI(api_key=LLMConfig.api_key, base_url=LLMConfig.api_base)
        self.model = LLMConfig.model
        self.reasoner_model = LLMConfig.reasoner_model
        self.max_tokens = LLMConfig.max_tokens
        self.temperature = LLMConfig.temperature
        self.max_retries = 3
        self.retry_delay = 2

    @classmethod
    def get_instance(cls) -> DeepSeekProvider:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def is_available() -> bool:
        return LLMConfig.is_configured()

    @staticmethod
    def _messages(messages: list[dict], system_prompt: str | None) -> list[dict]:
        return ([{"role": "system", "content": system_prompt}] if system_prompt else []) + list(
            messages
        )

    def _retry(self, operation):
        for attempt in range(self.max_retries):
            try:
                return operation()
            except Exception as error:
                logger.warning(
                    "DeepSeek request failed (%d/%d): %s",
                    attempt + 1,
                    self.max_retries,
                    error,
                )
                if attempt == self.max_retries - 1:
                    raise RuntimeError(
                        f"DeepSeek API failed after {self.max_retries} attempts: {error}"
                    ) from error
                time.sleep(self.retry_delay * (2**attempt))
        raise RuntimeError("unreachable")

    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
    ) -> str:
        response = self._retry(
            lambda: self._client.chat.completions.create(
                model=model or self.model,
                messages=self._messages(messages, system_prompt),
                temperature=self.temperature if temperature is None else temperature,
                max_tokens=max_tokens or self.max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
                stream=False,
            )
        )
        return response.choices[0].message.content or ""

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        tool_choice: str | dict = "auto",
    ) -> dict:
        response = self._retry(
            lambda: self._client.chat.completions.create(
                model=model or self.model,
                messages=self._messages(messages, system_prompt),
                temperature=self.temperature if temperature is None else temperature,
                max_tokens=max_tokens or self.max_tokens,
                tools=tools,
                tool_choice=tool_choice,
                extra_body={"thinking": {"type": "disabled"}},
                stream=False,
            )
        )
        choice = response.choices[0]
        parsed_calls = []
        for call in choice.message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = {}
            parsed_calls.append({"id": call.id, "name": call.function.name, "arguments": arguments})
        return {
            "content": choice.message.content,
            "tool_calls": parsed_calls or None,
            "finish_reason": choice.finish_reason,
            "usage": _usage_dict(getattr(response, "usage", None)),
        }

    def chat_stream(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        usage_callback: Callable[[dict[str, int]], None] | None = None,
    ) -> Generator[str, None, None]:
        full_messages = self._messages(messages, system_prompt)
        for attempt in range(self.max_retries):
            try:
                stream = self._client.chat.completions.create(
                    model=model or self.model,
                    messages=full_messages,
                    temperature=self.temperature if temperature is None else temperature,
                    max_tokens=max_tokens or self.max_tokens,
                    extra_body={"thinking": {"type": "disabled"}},
                    stream=True,
                    stream_options={"include_usage": True},
                )
                for chunk in stream:
                    usage = _usage_dict(getattr(chunk, "usage", None))
                    if usage and usage_callback:
                        usage_callback(usage)
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return
            except Exception as error:
                logger.warning(
                    "DeepSeek stream failed (%d/%d): %s",
                    attempt + 1,
                    self.max_retries,
                    error,
                )
                if attempt == self.max_retries - 1:
                    raise RuntimeError(
                        f"DeepSeek stream failed after {self.max_retries} attempts: {error}"
                    ) from error
                time.sleep(self.retry_delay * (2**attempt))

    def chat_with_reasoning(self, messages: list[dict], **kwargs) -> str:
        system_prompt = kwargs.pop("system_prompt", None)
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        reasoning_effort = kwargs.pop("reasoning_effort", "high")
        response = self._retry(
            lambda: self._client.chat.completions.create(
                model=self.reasoner_model,
                messages=self._messages(messages, system_prompt),
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
                extra_body={"thinking": {"type": "enabled"}},
                stream=False,
                **kwargs,
            )
        )
        return response.choices[0].message.content or ""

    @classmethod
    def reset(cls) -> None:
        cls._instance = None
