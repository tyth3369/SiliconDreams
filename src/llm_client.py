"""
SiliconDreams — DeepSeek LLM Client
====================================
封装 DeepSeek API 调用（兼容 OpenAI SDK）。
支持流式/非流式、自动重试、模型切换。
"""

import time
import logging
from typing import Generator, Optional
from openai import OpenAI

from config import LLMConfig

logger = logging.getLogger(__name__)


class DeepSeekClient:
    """
    DeepSeek API 客户端（单例）。

    用法:
        client = DeepSeekClient.get_instance()
        response = client.chat("你好")
        for chunk in client.chat_stream("你好"):
            print(chunk, end="")
    """

    _instance: Optional["DeepSeekClient"] = None

    def __init__(self):
        if not LLMConfig.is_configured():
            raise ValueError(
                "DeepSeek API Key 未配置。请在 .env 文件中设置 DEEPSEEK_API_KEY。\n"
                "获取 Key: https://platform.deepseek.com/api_keys"
            )
        self._client = OpenAI(
            api_key=LLMConfig.api_key,
            base_url=LLMConfig.api_base,
        )
        self.model = LLMConfig.model
        self.reasoner_model = LLMConfig.reasoner_model
        self.max_tokens = LLMConfig.max_tokens
        self.temperature = LLMConfig.temperature
        self.max_retries = 3
        self.retry_delay = 2  # 秒

    @classmethod
    def get_instance(cls) -> "DeepSeekClient":
        """获取单例实例（惰性初始化）"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def is_available(cls) -> bool:
        """检查 API Key 是否已配置"""
        return LLMConfig.is_configured()

    # ── 非流式调用（Agent 工具链使用）─────────────────

    def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        同步调用，返回完整回复文本。

        Args:
            messages: [{"role": "user"|"assistant"|"system", "content": "..."}]
            model: 模型名（默认使用 config 中的模型）
            temperature: 温度（默认使用 config 中的温度）
            max_tokens: 最大 token 数
            system_prompt: 系统提示词（会插入 messages 开头）

        Returns:
            AI 回复文本
        """
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        model = model or self.model
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens or self.max_tokens

        for attempt in range(self.max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                )
                return response.choices[0].message.content or ""

            except Exception as e:
                logger.warning(f"DeepSeek API 调用失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))  # 指数退避
                else:
                    raise RuntimeError(f"DeepSeek API 调用失败，已重试 {self.max_retries} 次: {e}")

    # ── Tool Calling（Agent Loop 使用）───────────────────

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> dict:
        """
        Non-streaming call with tool/function calling support.

        Args:
            messages: Chat messages
            tools: OpenAI-format tool definitions
            model: Model override
            temperature: Temperature override
            max_tokens: Max tokens override
            system_prompt: System prompt (prepended to messages)

        Returns:
            {
                "content": str | None,       # Final text (None when tool_calls present)
                "tool_calls": list | None,   # [{"id": ..., "name": ..., "arguments": {...}}]
                "finish_reason": str,
            }
        """
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        model = model or self.model
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens or self.max_tokens

        for attempt in range(self.max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    stream=False,
                )
                choice = response.choices[0]
                msg = choice.message

                # Parse tool_calls if present
                tool_calls = None
                if msg.tool_calls:
                    tool_calls = []
                    for tc in msg.tool_calls:
                        # Parse JSON arguments string
                        import json
                        try:
                            args = json.loads(tc.function.arguments)
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        tool_calls.append({
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": args,
                        })

                return {
                    "content": msg.content,
                    "tool_calls": tool_calls,
                    "finish_reason": choice.finish_reason,
                }

            except Exception as e:
                logger.warning(
                    f"DeepSeek Tool Calling 失败 (尝试 {attempt + 1}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))
                else:
                    raise RuntimeError(
                        f"DeepSeek API 调用失败，已重试 {self.max_retries} 次: {e}"
                    )

    # ── 流式调用（聊天界面实时显示）───────────────────

    def chat_stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        流式调用，逐 chunk yield 回复文本。

        Args:
            同 chat()

        Yields:
            每次 yield 一段文本增量
        """
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        model = model or self.model
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens or self.max_tokens

        for attempt in range(self.max_retries):
            try:
                stream = self._client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
                for chunk in stream:
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return  # 正常完成

            except Exception as e:
                logger.warning(f"DeepSeek 流式调用失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))
                else:
                    yield f"\n\n> [ERROR] API call failed: {e}"

    # ── 推理模型（复杂任务）───────────────────────────

    def chat_with_reasoning(
        self,
        messages: list[dict],
        **kwargs,
    ) -> str:
        """
        使用 deepseek-reasoner (R1) 进行深度推理。
        适用于多步分析、复杂财务计算验证等场景。
        """
        return self.chat(messages, model=self.reasoner_model, **kwargs)


# ── 便捷函数 ──────────────────────────────────────────

def get_llm() -> DeepSeekClient:
    """获取 LLM 客户端（便捷函数，供 LangChain 集成使用）"""
    return DeepSeekClient.get_instance()


def llm_available() -> bool:
    """检查 LLM 是否可用"""
    return DeepSeekClient.is_available()
