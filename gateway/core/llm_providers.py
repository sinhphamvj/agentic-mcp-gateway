# SPDX-License-Identifier: Apache-2.0
"""LLM provider abstractions.

Supports OpenAI-compatible APIs (OpenAI, NVIDIA NIM, Ollama) via
``AsyncOpenAI`` and Anthropic's native API via ``AsyncAnthropic``.
Message format conversion is handled transparently so the orchestrator
always works with OpenAI-shaped dicts regardless of the backend.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any, cast

from openai import AsyncOpenAI
from pydantic import BaseModel

from gateway.core.models import LLMConfig, LLMProvider
from gateway.observability.tracer import trace_llm_call

_PROVIDER_BASE_URLS: dict[LLMProvider, str] = {
    LLMProvider.OPENAI: "https://api.openai.com/v1",
    LLMProvider.NVIDIA_NIM: "https://integrate.api.nvidia.com/v1",
    LLMProvider.ANTHROPIC: "https://api.anthropic.com/v1",
    LLMProvider.OLLAMA: "http://localhost:11434/v1",
}


class LLMClient:
    """Async LLM client that dispatches to OpenAI or Anthropic backends.

    The orchestrator always sends and receives OpenAI-shaped dicts; this
    class converts to the provider's native format when needed.
    """

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client: Any
        self._anthropic: bool
        if config.provider == LLMProvider.ANTHROPIC:
            from anthropic import AsyncAnthropic

            api_key = os.environ.get(config.api_key_env, "no-key-set")
            self._client = AsyncAnthropic(api_key=api_key)
            self._anthropic = True
        else:
            base_url = config.base_url or _PROVIDER_BASE_URLS.get(config.provider, "")
            api_key = os.environ.get(config.api_key_env, "no-key-set")
            self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
            self._anthropic = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
            Provider response in OpenAI-compatible shape (the caller
            uses ``_first_response_message`` / ``_message_tool_calls``
            to extract fields).
        """
        if self._anthropic:
            return await self._anthropic_chat(messages, tools)
        return await self._openai_chat(messages, tools)

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

        Raises:
            ValueError: If the model output cannot be parsed.
        """
        if self._anthropic:
            return await self._anthropic_structured_output(messages, response_model)
        return await self._openai_structured_output(messages, response_model)

    # ------------------------------------------------------------------
    # OpenAI backend
    # ------------------------------------------------------------------

    async def _openai_chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
    ) -> Any:
        kwargs: dict[str, object] = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools is not None:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        with trace_llm_call(self.config.provider.value, self.config.model_name) as span:
            response = await self._client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
            if span is not None:
                usage = getattr(response, "usage", None)
                if usage is not None:
                    total = getattr(usage, "total_tokens", 0) or 0
                    span.set_attribute("llm.tokens", total)
            return response

    async def _openai_structured_output(
        self,
        messages: list[dict[str, object]],
        response_model: type[BaseModel],
    ) -> BaseModel:
        with trace_llm_call(self.config.provider.value, self.config.model_name):
            response = await self._client.beta.chat.completions.parse(
                model=self.config.model_name,
                messages=messages,  # type: ignore[arg-type]
                response_format=response_model,
                temperature=self.config.temperature,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise ValueError("Failed to parse response schema.")
            return parsed

    # ------------------------------------------------------------------
    # Anthropic backend
    # ------------------------------------------------------------------

    async def _anthropic_chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
    ) -> Any:
        anthropic_msgs, system = _to_anthropic_messages(messages)
        kwargs: dict[str, object] = {
            "model": self.config.model_name,
            "messages": anthropic_msgs,
            "max_tokens": self.config.max_tokens,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)

        with trace_llm_call(self.config.provider.value, self.config.model_name) as span:
            response = await self._client.messages.create(**kwargs)  # type: ignore[call-overload]
            if span is not None:
                usage = getattr(response, "usage", None)
                if usage is not None:
                    total = (usage.input_tokens or 0) + (usage.output_tokens or 0)
                    span.set_attribute("llm.tokens", total)
            return _from_anthropic_response(response)

    async def _anthropic_structured_output(
        self,
        messages: list[dict[str, object]],
        response_model: type[BaseModel],
    ) -> BaseModel:
        anthropic_msgs, system = _to_anthropic_messages(messages)
        schema = response_model.model_json_schema()
        tool_name = response_model.__name__.lower()

        kwargs: dict[str, object] = {
            "model": self.config.model_name,
            "messages": anthropic_msgs,
            "max_tokens": self.config.max_tokens,
            "tools": [
                {
                    "name": tool_name,
                    "description": f"Structured output matching {response_model.__name__}",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": tool_name},
        }
        if system:
            kwargs["system"] = system

        with trace_llm_call(self.config.provider.value, self.config.model_name):
            response = await self._client.messages.create(**kwargs)  # type: ignore[call-overload]
            for block in response.content:
                if block.type == "tool_use" and block.name == tool_name:
                    return response_model.model_validate(block.input)
            raise ValueError("Failed to parse response schema.")


# ------------------------------------------------------------------
# Format adapters
# ------------------------------------------------------------------


def _to_anthropic_messages(
    openai_messages: list[dict[str, object]],
) -> tuple[list[dict[str, object]], str | None]:
    """Convert OpenAI message format to Anthropic format.

    Returns ``(messages, system_prompt)``.  Anthropic expects the
    system prompt as a top-level parameter rather than a message role.
    """
    system: str | None = None
    messages: list[dict[str, object]] = []

    for msg in openai_messages:
        role = str(msg.get("role", "user"))
        content = msg.get("content")

        if role == "system":
            system = str(content) if content else None
        elif role == "user":
            messages.append({"role": "user", "content": str(content) if content else ""})
        elif role == "assistant":
            blocks: list[dict[str, object]] = []
            if content:
                blocks.append({"type": "text", "text": str(content)})
            tool_calls_raw = msg.get("tool_calls")
            if tool_calls_raw:
                for tc in cast("list[Any]", tool_calls_raw):
                    tc_id = _get(tc, "id", "")
                    func = _get(tc, "function", {})
                    tc_name = _get(func, "name", "")
                    raw_args = _get(func, "arguments", "{}")
                    if isinstance(raw_args, str):
                        try:
                            parsed = json.loads(raw_args)
                        except json.JSONDecodeError:
                            parsed = {}
                    else:
                        parsed = raw_args
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc_id,
                            "name": tc_name,
                            "input": parsed,
                        }
                    )
            messages.append(
                {"role": "assistant", "content": blocks}
                if blocks
                else {"role": "assistant", "content": ""}
            )
        elif role == "tool":
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": str(msg.get("tool_call_id", "")),
                            "content": str(content) if content else "",
                        }
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": str(content) if content else ""})

    return messages, system


def _to_anthropic_tools(openai_tools: list[dict[str, object]]) -> list[dict[str, object]]:
    """Convert OpenAI tool format to Anthropic tool format.

    OpenAI wraps tools in ``{"type": "function", "function": {...}}``.
    Anthropic expects ``{"name": ..., "description": ..., "input_schema": ...}``.
    """
    result: list[dict[str, object]] = []
    for tool in openai_tools:
        func = _get(tool, "function", tool)
        result.append(
            {
                "name": _get(func, "name", ""),
                "description": _get(func, "description", ""),
                "input_schema": _get(func, "parameters", {"type": "object", "properties": {}}),
            }
        )
    return result


def _from_anthropic_response(response: object) -> Any:
    """Convert an Anthropic message response to OpenAI-compatible shape.

    The returned object exposes ``choices[0].message.content`` and
    ``choices[0].message.tool_calls`` so the orchestrator's existing
    ``_first_response_message`` / ``_message_tool_calls`` helpers work
    without changes.
    """
    content_blocks: list[Any] = _get(response, "content", [])

    text_content = ""
    tool_calls: list[Any] = []

    for block in content_blocks:
        block_type = _get(block, "type", "")
        if block_type == "text":
            text_content = str(_get(block, "text", ""))
        elif block_type == "tool_use":
            block_input = _get(block, "input", {})
            tool_calls.append(
                SimpleNamespace(
                    id=str(_get(block, "id", "")),
                    function=SimpleNamespace(
                        name=str(_get(block, "name", "")),
                        arguments=(
                            json.dumps(block_input, ensure_ascii=False)
                            if isinstance(block_input, dict)
                            else str(block_input)
                        ),
                    ),
                )
            )

    usage = _get(response, "usage", None)
    total_tokens = 0
    if usage is not None:
        inp = _get(usage, "input_tokens", 0) or 0
        out = _get(usage, "output_tokens", 0) or 0
        total_tokens = inp + out

    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=text_content if text_content else None,
                    tool_calls=tool_calls if tool_calls else None,
                )
            )
        ],
        usage=SimpleNamespace(total_tokens=total_tokens),
    )


def _get(item: Any, name: str, default: Any = None) -> Any:
    """Safely get an attribute from a dict, SimpleNamespace, or object."""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)
