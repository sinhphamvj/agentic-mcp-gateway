# SPDX-License-Identifier: Apache-2.0
"""LLM provider abstractions."""

from __future__ import annotations

import os
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel

from gateway.core.models import LLMConfig, LLMProvider
from gateway.observability.tracer import trace_llm_call


class LLMClient:
    """OpenAI-compatible async client for configured LLM providers."""

    PROVIDER_DEFAULTS: dict[LLMProvider, str] = {
        LLMProvider.OPENAI: "https://api.openai.com/v1",
        LLMProvider.NVIDIA_NIM: "https://integrate.api.nvidia.com/v1",
        LLMProvider.ANTHROPIC: "https://api.anthropic.com/v1",
        LLMProvider.OLLAMA: "http://localhost:11434/v1",
    }

    def __init__(self, config: LLMConfig) -> None:
        """Initialize the underlying async client.

        Args:
            config: LLM provider configuration.
        """
        self.config = config
        base_url = config.base_url or self.PROVIDER_DEFAULTS[config.provider]
        api_key = os.environ.get(config.api_key_env, "no-key-set")
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> Any:
        """Send a chat completion request.

        Args:
            messages: OpenAI-compatible chat messages.
            tools: Optional OpenAI-compatible tool definitions.

        Returns:
            Provider response object.
        """
        kwargs: dict[str, object] = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools is not None:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        with trace_llm_call(
            self.config.provider.value,
            self.config.model_name,
        ) as span:
            response = await self._client.chat.completions.create(**kwargs)
            if span is not None:
                usage = getattr(response, "usage", None)
                if usage is not None:
                    total = getattr(usage, "total_tokens", 0) or 0
                    span.set_attribute("llm.tokens", total)
            return response

    async def structured_output(
        self,
        messages: list[dict[str, object]],
        response_model: type[BaseModel],
    ) -> BaseModel:
        """Return a parsed structured response.

        Args:
            messages: OpenAI-compatible chat messages.
            response_model: Pydantic model type to parse into.

        Returns:
            Parsed Pydantic object.
        """
        with trace_llm_call(
            self.config.provider.value,
            self.config.model_name,
        ):
            response = await self._client.beta.chat.completions.parse(
                model=self.config.model_name,
                messages=messages,
                response_format=response_model,
                temperature=self.config.temperature,
            )
            return response.choices[0].message.parsed

