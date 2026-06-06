# SPDX-License-Identifier: Apache-2.0
"""Shared data models for the gateway."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class LLMProvider(str, Enum):  # noqa: UP042
    """Supported LLM provider identifiers."""

    OPENAI = "openai"
    NVIDIA_NIM = "nvidia-nim"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


class LLMConfig(BaseModel):
    """Configuration for one LLM provider."""

    provider: LLMProvider
    model_name: str
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 4096


class MCPServerConfig(BaseModel):
    """Configuration for one MCP server connection."""

    name: str
    transport: str = "http"
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    description: str = ""


class IntentConfig(BaseModel):
    """Configuration for routing one user intent."""

    name: str
    description: str
    mcp_server: str
    system_prompt: str = ""


class WorkflowConfig(BaseModel):
    """Top-level workflow configuration parsed from YAML."""

    llm: LLMConfig
    mcp_servers: list[MCPServerConfig]
    intents: list[IntentConfig]
    gateway_port: int = 8001
    enable_tracing: bool = True
    human_in_the_loop_intents: list[str] = Field(default_factory=list)
    max_tool_rounds: int = 3


class ToolSchema(BaseModel):
    """Normalized tool schema used for LLM tool calling."""

    name: str
    description: str
    parameters: dict[str, object]
    server_name: str
