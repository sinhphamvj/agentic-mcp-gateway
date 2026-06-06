# SPDX-License-Identifier: Apache-2.0
"""Tests for workflow config models and LLM provider abstraction."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from gateway.core.config import load_config
from gateway.core.llm_providers import LLMClient
from gateway.core.models import (
    IntentConfig,
    LLMConfig,
    LLMProvider,
    MCPServerConfig,
    ToolSchema,
    WorkflowConfig,
)


class FakeChatCompletions:
    """Fake OpenAI chat completions endpoint."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> dict[str, Any] | Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):

            async def _stream():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="Hello", tool_calls=None),
                        )
                    ],
                    usage=None,
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=" world", tool_calls=None),
                        )
                    ],
                    usage=SimpleNamespace(
                        model_dump=lambda: {
                            "prompt_tokens": 5,
                            "completion_tokens": 7,
                        }
                    ),
                )

            return _stream()

        return {"created": kwargs}


class FakeBetaChatCompletions:
    """Fake OpenAI structured-output parse endpoint."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        response_model = kwargs["response_format"]
        message = type("FakeMessage", (), {"parsed": response_model(answer="yes")})()
        return type(
            "FakeParsedResponse",
            (),
            {
                "choices": [
                    type(
                        "FakeChoice",
                        (),
                        {"message": message},
                    )()
                ]
            },
        )()


class FakeAsyncOpenAI:
    """Fake AsyncOpenAI client that records constructor inputs."""

    instances: list[FakeAsyncOpenAI] = []

    def __init__(self, *, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.chat_completions = FakeChatCompletions()
        self.beta_chat_completions = FakeBetaChatCompletions()
        self.chat = type(
            "FakeChat",
            (),
            {"completions": self.chat_completions},
        )()
        self.beta = type(
            "FakeBeta",
            (),
            {
                "chat": type(
                    "FakeBetaChat",
                    (),
                    {"completions": self.beta_chat_completions},
                )()
            },
        )()
        self.instances.append(self)


class FakeAnthropicMessages:
    """Fake Anthropic messages endpoint."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):

            async def _stream():
                yield {
                    "type": "content_block_start",
                    "content_block": {"type": "text", "text": "Hello"},
                }
                yield {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": " from"},
                }
                yield {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": " Claude"},
                }
                yield {
                    "type": "message_delta",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                }

            return _stream()

        tool_name = kwargs.get("tool_choice", {}).get("name")
        if tool_name:
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="tu_1",
                        name=tool_name,
                        input={"answer": "yes"},
                    )
                ],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="Hello from Claude"),
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


class FakeAsyncAnthropic:
    """Fake AsyncAnthropic client that records constructor inputs."""

    instances: list[FakeAsyncAnthropic] = []

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.messages = FakeAnthropicMessages()
        self.instances.append(self)


class AnswerModel(BaseModel):
    """Structured response model used by tests."""

    answer: str


def test_llm_provider_enum_values() -> None:
    """LLM providers use stable config values."""
    assert LLMProvider.OPENAI == "openai"
    assert LLMProvider.NVIDIA_NIM == "nvidia-nim"
    assert LLMProvider.ANTHROPIC == "anthropic"
    assert LLMProvider.OLLAMA == "ollama"


def test_pydantic_model_defaults_and_validation() -> None:
    """Pydantic models expose requested fields and sensible defaults."""
    llm_config = LLMConfig(provider=LLMProvider.OPENAI, model_name="gpt-4.1-mini")
    assert llm_config.base_url is None
    assert llm_config.api_key_env == "OPENAI_API_KEY"
    assert llm_config.temperature == 0.0
    assert llm_config.max_tokens == 4096

    mcp_server = MCPServerConfig(name="db")
    assert mcp_server.transport == "http"
    assert mcp_server.url is None
    assert mcp_server.command is None
    assert mcp_server.args == []
    assert mcp_server.description == ""

    intent = IntentConfig(name="lookup", description="Lookup invoices", mcp_server="db")
    assert intent.system_prompt == ""

    tool_schema = ToolSchema(
        name="query",
        description="Run a query",
        parameters={"type": "object"},
        server_name="db",
    )
    assert tool_schema.parameters == {"type": "object"}

    workflow = WorkflowConfig(llm=llm_config, mcp_servers=[mcp_server], intents=[intent])
    assert workflow.gateway_port == 8001
    assert workflow.enable_tracing is True
    assert workflow.human_in_the_loop_intents == []

    with pytest.raises(ValidationError):
        LLMConfig(provider="unsupported", model_name="model")


def test_load_config_parses_yaml_and_substitutes_env_vars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_config reads YAML, substitutes environment variables, and validates."""
    monkeypatch.setenv("MODEL_NAME", "gpt-4.1-mini")
    monkeypatch.setenv("API_KEY_ENV_NAME", "CUSTOM_OPENAI_API_KEY")
    monkeypatch.setenv("SERVER_URL", "http://localhost:8000/mcp")

    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(
        """
llm:
  provider: openai
  model_name: ${MODEL_NAME}
  api_key_env: ${API_KEY_ENV_NAME}
  temperature: 0.2
  max_tokens: 1024
mcp_servers:
  - name: db
    transport: http
    url: ${SERVER_URL}
    description: Database tools
intents:
  - name: lookup
    description: Lookup invoices
    mcp_server: db
    system_prompt: Use database tools.
gateway_port: 9000
enable_tracing: false
human_in_the_loop_intents:
  - refund
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.llm.provider is LLMProvider.OPENAI
    assert config.llm.model_name == "gpt-4.1-mini"
    assert config.llm.api_key_env == "CUSTOM_OPENAI_API_KEY"
    assert config.llm.temperature == 0.2
    assert config.llm.max_tokens == 1024
    assert config.mcp_servers[0].url == "http://localhost:8000/mcp"
    assert config.intents[0].system_prompt == "Use database tools."
    assert config.gateway_port == 9000
    assert config.enable_tracing is False
    assert config.human_in_the_loop_intents == ["refund"]


def test_load_config_raises_for_missing_file(tmp_path: Path) -> None:
    """load_config reports missing YAML paths clearly."""
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config(tmp_path / "missing.yaml")


def test_load_config_validates_missing_required_fields(tmp_path: Path) -> None:
    """load_config surfaces Pydantic validation errors for malformed workflows."""
    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(
        """
llm:
  provider: openai
mcp_servers: []
intents: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_config(config_path)


@pytest.mark.parametrize(
    ("provider", "expected_base_url", "api_key_env"),
    [
        (LLMProvider.OPENAI, "https://api.openai.com/v1", "OPENAI_API_KEY"),
        (LLMProvider.NVIDIA_NIM, "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
        (LLMProvider.OLLAMA, "http://localhost:11434/v1", "OLLAMA_API_KEY"),
    ],
)
def test_llm_client_initializes_async_openai_for_providers(
    provider: LLMProvider,
    expected_base_url: str,
    api_key_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLMClient passes the expected base URL and API key to AsyncOpenAI."""
    import gateway.core.llm_providers as llm_module

    FakeAsyncOpenAI.instances = []
    monkeypatch.setattr(llm_module, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setenv(api_key_env, f"secret-for-{provider.value}")

    client = LLMClient(
        LLMConfig(
            provider=provider,
            model_name="test-model",
            api_key_env=api_key_env,
        )
    )

    assert client.config.provider is provider
    assert FakeAsyncOpenAI.instances[0].base_url == expected_base_url
    assert FakeAsyncOpenAI.instances[0].api_key == f"secret-for-{provider.value}"


def test_llm_client_prefers_configured_base_url_and_falls_back_to_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLMClient honors config base_url and uses a harmless placeholder key if absent."""
    import gateway.core.llm_providers as llm_module

    FakeAsyncOpenAI.instances = []
    monkeypatch.setattr(llm_module, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.delenv("MISSING_API_KEY_ENV", raising=False)

    LLMClient(
        LLMConfig(
            provider=LLMProvider.OPENAI,
            model_name="test-model",
            base_url="http://custom.local/v1",
            api_key_env="MISSING_API_KEY_ENV",
        )
    )

    assert FakeAsyncOpenAI.instances[0].base_url == "http://custom.local/v1"
    assert FakeAsyncOpenAI.instances[0].api_key == "no-key-set"


@pytest.mark.asyncio
async def test_llm_client_chat_passes_model_options_and_optional_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chat forwards model settings, messages, and optional tools."""
    import gateway.core.llm_providers as llm_module

    FakeAsyncOpenAI.instances = []
    monkeypatch.setattr(llm_module, "AsyncOpenAI", FakeAsyncOpenAI)

    client = LLMClient(
        LLMConfig(
            provider=LLMProvider.OPENAI,
            model_name="gpt-test",
            temperature=0.3,
            max_tokens=128,
        )
    )
    messages = [{"role": "user", "content": "hi"}]
    tools = [{"type": "function", "function": {"name": "lookup"}}]

    response = await client.chat(messages, tools=tools)

    kwargs = FakeAsyncOpenAI.instances[0].chat_completions.calls[0]
    assert response == {"created": kwargs}
    assert kwargs["model"] == "gpt-test"
    assert kwargs["messages"] == messages
    assert kwargs["temperature"] == 0.3
    assert kwargs["max_tokens"] == 128
    assert kwargs["tools"] == tools
    assert kwargs["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_llm_client_structured_output_returns_pydantic_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """structured_output returns the parsed Pydantic object from OpenAI."""
    import gateway.core.llm_providers as llm_module

    FakeAsyncOpenAI.instances = []
    monkeypatch.setattr(llm_module, "AsyncOpenAI", FakeAsyncOpenAI)

    client = LLMClient(LLMConfig(provider=LLMProvider.OPENAI, model_name="gpt-test"))
    messages = [{"role": "user", "content": "answer yes"}]

    parsed = await client.structured_output(messages, AnswerModel)

    kwargs = FakeAsyncOpenAI.instances[0].beta_chat_completions.calls[0]
    assert parsed == AnswerModel(answer="yes")
    assert kwargs["model"] == "gpt-test"
    assert kwargs["messages"] == messages
    assert kwargs["response_format"] is AnswerModel
    assert kwargs["temperature"] == 0.0


# ------------------------------------------------------------------
# Anthropic provider tests
# ------------------------------------------------------------------


def test_anthropic_client_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLMClient instantiates AsyncAnthropic for the ANTHROPIC provider."""
    FakeAsyncAnthropic.instances = []
    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")

    client = LLMClient(
        LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model_name="claude-sonnet-4-20250514",
            api_key_env="ANTHROPIC_API_KEY",
        )
    )

    assert client.config.provider is LLMProvider.ANTHROPIC
    assert FakeAsyncAnthropic.instances[0].api_key == "sk-ant-secret"
    assert client._anthropic is True


@pytest.mark.asyncio
async def test_anthropic_chat_text_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat() with Anthropic returns OpenAI-shaped text response."""
    FakeAsyncAnthropic.instances = []
    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")

    client = LLMClient(
        LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model_name="claude-sonnet-4-20250514",
            api_key_env="ANTHROPIC_API_KEY",
            max_tokens=512,
        )
    )
    messages = [{"role": "user", "content": "Say hello"}]
    response = await client.chat(messages)

    kwargs = FakeAsyncAnthropic.instances[0].messages.calls[0]
    assert kwargs["model"] == "claude-sonnet-4-20250514"
    assert kwargs["messages"] == [{"role": "user", "content": "Say hello"}]
    assert kwargs["max_tokens"] == 512
    assert "system" not in kwargs

    assert response.choices[0].message.content == "Hello from Claude"
    assert response.choices[0].message.tool_calls is None


@pytest.mark.asyncio
async def test_anthropic_chat_with_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat() with Anthropic forwards tools in Anthropic format."""
    FakeAsyncAnthropic.instances = []
    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")

    client = LLMClient(
        LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model_name="claude-sonnet-4-20250514",
            api_key_env="ANTHROPIC_API_KEY",
            max_tokens=512,
        )
    )
    messages = [{"role": "user", "content": "Use a tool"}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Lookup data",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    await client.chat(messages, tools=tools)

    kwargs = FakeAsyncAnthropic.instances[0].messages.calls[0]
    assert "tools" in kwargs
    assert kwargs["tools"] == [
        {
            "name": "lookup",
            "description": "Lookup data",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]


@pytest.mark.asyncio
async def test_anthropic_chat_extracts_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat() with Anthropic extracts system message from the list."""
    FakeAsyncAnthropic.instances = []
    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")

    client = LLMClient(
        LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model_name="claude-sonnet-4-20250514",
            api_key_env="ANTHROPIC_API_KEY",
            max_tokens=512,
        )
    )
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hi"},
    ]
    await client.chat(messages)

    kwargs = FakeAsyncAnthropic.instances[0].messages.calls[0]
    assert kwargs["system"] == "You are helpful."
    assert kwargs["messages"] == [{"role": "user", "content": "Hi"}]


@pytest.mark.asyncio
async def test_anthropic_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """structured_output() with Anthropic returns parsed Pydantic object."""
    FakeAsyncAnthropic.instances = []
    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")

    client = LLMClient(
        LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model_name="claude-sonnet-4-20250514",
            api_key_env="ANTHROPIC_API_KEY",
            max_tokens=512,
        )
    )
    messages = [{"role": "user", "content": "Answer yes"}]
    parsed = await client.structured_output(messages, AnswerModel)

    kwargs = FakeAsyncAnthropic.instances[0].messages.calls[0]
    assert parsed == AnswerModel(answer="yes")
    assert kwargs["model"] == "claude-sonnet-4-20250514"
    assert kwargs["tool_choice"] == {"type": "tool", "name": "answermodel"}
    assert len(kwargs["tools"]) == 1
    assert kwargs["tools"][0]["name"] == "answermodel"


@pytest.mark.asyncio
async def test_anthropic_chat_tool_call_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat() with Anthropic returns OpenAI-shaped tool_calls when Claude uses tools."""
    FakeAsyncAnthropic.instances = []

    class FakeToolUseMessages:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def create(self, **kwargs: Any) -> Any:
            self.calls.append(kwargs)
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="tu_abc",
                        name="lookup",
                        input={"key": "value"},
                    ),
                ],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )

    class FakeToolUsingAnthropic:
        instances: list[FakeToolUsingAnthropic] = []

        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.messages = FakeToolUseMessages()
            self.instances.append(self)

    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeToolUsingAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")

    client = LLMClient(
        LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model_name="claude-sonnet-4-20250514",
            api_key_env="ANTHROPIC_API_KEY",
            max_tokens=512,
        )
    )
    messages = [{"role": "user", "content": "Use lookup tool"}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Lookup",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    response = await client.chat(messages, tools=tools)

    assert response.choices[0].message.content is None
    assert response.choices[0].message.tool_calls is not None
    assert len(response.choices[0].message.tool_calls) == 1
    tc = response.choices[0].message.tool_calls[0]
    assert tc.id == "tu_abc"
    assert tc.function.name == "lookup"
    assert tc.function.arguments == '{"key": "value"}'


# ------------------------------------------------------------------
# Streaming tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_stream_chat_yields_text_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    """stream_chat with OpenAI yields text deltas and a done event."""
    import gateway.core.llm_providers as llm_module

    FakeAsyncOpenAI.instances = []
    monkeypatch.setattr(llm_module, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")

    client = LLMClient(
        LLMConfig(
            provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
            api_key_env="OPENAI_API_KEY",
        )
    )
    messages = [{"role": "user", "content": "Say hello"}]

    events: list[tuple[str, object]] = []
    async for event in client.stream_chat(messages):
        events.append(event)

    assert ("delta", "Hello") in events
    assert ("delta", " world") in events
    assert ("usage", {"prompt_tokens": 5, "completion_tokens": 7}) in events
    assert events[-1] == ("done", None)


@pytest.mark.asyncio
async def test_anthropic_stream_chat_yields_text_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    """stream_chat with Anthropic yields text deltas and a done event."""
    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")

    client = LLMClient(
        LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model_name="claude-sonnet-4-20250514",
            api_key_env="ANTHROPIC_API_KEY",
            max_tokens=512,
        )
    )
    messages = [{"role": "user", "content": "Say hello"}]

    events: list[tuple[str, object]] = []
    async for event in client.stream_chat(messages):
        events.append(event)

    assert ("delta", "Hello") in events
    assert ("delta", " from") in events
    assert ("delta", " Claude") in events
    assert events[-1] == ("done", None)
