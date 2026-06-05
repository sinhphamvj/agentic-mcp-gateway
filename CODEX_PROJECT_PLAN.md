# CODEX PROJECT PLAN — agentic-mcp-gateway

> **Mục tiêu:** Xây dựng open-source framework giúp developer nhanh chóng tạo
> agent workflows kết nối nhiều MCP servers, hoạt động với bất kỳ LLM backend nào.
>
> **Phương pháp:** Dùng Codex App với tính năng `/goal` để thực hiện từng phase.
>
> **Ngày tạo:** 2026-06-05
> **Author:** sinhpham
> **License:** Apache-2.0
> **Target:** ≥1,000 GitHub stars → Apply OpenAI Codex for OSS

---

## Mục lục

- [AGENTS.md — Cho Codex hiểu project](#agentsmd--cho-codex-hiểu-project)
- [Phase 0 — Project Scaffolding](#phase-0--project-scaffolding)
- [Phase 1 — Core MCP Client Infrastructure](#phase-1--core-mcp-client-infrastructure)
- [Phase 2 — LLM Provider Abstraction](#phase-2--llm-provider-abstraction)
- [Phase 3 — LangGraph Router & Orchestrator](#phase-3--langgraph-router--orchestrator)
- [Phase 4 — Example MCP Servers](#phase-4--example-mcp-servers)
- [Phase 5 — Agent Skills & OpenClaw Integration](#phase-5--agent-skills--openclaw-integration)
- [Phase 6 — Observability & Tracing](#phase-6--observability--tracing)
- [Phase 7 — Full Demo Examples](#phase-7--full-demo-examples)
- [Phase 8 — Documentation & CI/CD](#phase-8--documentation--cicd)
- [Phase 9 — Polish & GitHub Stars Strategy](#phase-9--polish--github-stars-strategy)
- [Phase 10 — Apply OpenAI Codex for OSS](#phase-10--apply-openai-codex-for-oss)

---

## AGENTS.md — Cho Codex hiểu project

> **Hành động đầu tiên:** Tạo file `AGENTS.md` ở root repo với nội dung
> trong file AGENTS.md đi kèm. Codex sẽ đọc file này để hiểu toàn bộ
> context trước khi thực hiện bất kỳ goal nào.
>
> File `AGENTS.md` đã được chuẩn bị sẵn trong package này.

---

## Phase 0 — Project Scaffolding

### Codex Goal Command

```
/goal Initialize the agentic-mcp-gateway repository with complete project structure.

Create ALL of the following directories and files:

Root files:
- pyproject.toml (with all dependencies listed in AGENTS.md)
- AGENTS.md (already provided — copy from root)
- LICENSE (Apache-2.0 full text)
- .gitignore (Python + Node + .env + __pycache__ + .venv + dist/)
- README.md (placeholder with project name and "🚧 Under Construction")
- Makefile (targets: install, test, lint, format, serve, docker-up)

Directory structure:
gateway/
├── __init__.py
├── cli.py                    # CLI entrypoint (click or typer)
├── core/
│   ├── __init__.py
│   ├── config.py             # YAML config parser
│   ├── models.py             # Shared Pydantic models
│   ├── llm_providers.py      # Multi-provider LLM client
│   ├── router.py             # LangGraph intent classifier
│   ├── orchestrator.py       # Multi-MCP orchestration engine
│   └── state.py              # LangGraph state schema
├── mcp_client/
│   ├── __init__.py
│   ├── http_client.py        # Async MCP HTTP client
│   ├── stdio_client.py       # Stdio transport client
│   └── manager.py            # Multi-server connection manager
├── skills/
│   ├── __init__.py
│   └── generator.py          # Auto-generate SKILL.md from MCP schema
└── observability/
    ├── __init__.py
    └── tracer.py              # OpenTelemetry + Phoenix

servers/
├── database/
│   ├── pyproject.toml
│   ├── server.py
│   └── db_helper.py
├── rest_api/
│   ├── pyproject.toml
│   └── server.py
├── filesystem/
│   ├── pyproject.toml
│   └── server.py
└── template/
    └── cookiecutter.json

examples/
├── music-store/
│   ├── workflow.yaml
│   ├── README.md
│   └── data/
├── devops-assistant/
│   ├── workflow.yaml
│   └── README.md
└── research-agent/
    ├── workflow.yaml
    └── README.md

tests/
├── __init__.py
├── conftest.py
├── test_mcp_client.py
├── test_llm_providers.py
├── test_router.py
├── test_orchestrator.py
└── test_servers/
    ├── test_database_server.py
    └── test_rest_api_server.py

docs/
├── getting-started.md
├── architecture.md
└── create-mcp-server.md

.github/
└── workflows/
    ├── ci.yml
    └── release.yml

docker-compose.yml
Dockerfile

Every __init__.py should have a module docstring.
Every .py file should have Apache-2.0 SPDX header comment.
pyproject.toml must include [project.scripts] amcpg = "gateway.cli:main"

Stop when: `find . -name "*.py" | head -30` shows all expected files exist,
and `uv sync` completes without errors.
```

### Acceptance Criteria
- [ ] `uv sync` thành công
- [ ] Tất cả directories tồn tại
- [ ] `python -c "import gateway"` không lỗi
- [ ] `amcpg --help` hiển thị CLI help
- [ ] `.gitignore` bao gồm `.env`, `__pycache__`, `.venv`

---

## Phase 1 — Core MCP Client Infrastructure

### Dependencies: Phase 0

### Codex Goal Command

```
/goal Implement the MCP client infrastructure in gateway/mcp_client/.
These files enable the gateway to connect to any MCP server via HTTP or stdio.

### File 1: gateway/mcp_client/http_client.py

Implement class MCPHttpClient that connects to MCP servers via HTTP transport.
Pattern based on MCP SDK streamablehttp_client:

```python
"""Async MCP HTTP client for connecting to remote MCP servers."""

from contextlib import AsyncExitStack
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class MCPHttpClient:
    """MCP client that connects to servers via HTTP (Streamable HTTP transport).

    Usage:
        client = MCPHttpClient("http://localhost:8000/mcp")
        session = await client.connect()
        tools = await session.list_tools()
        result = await session.call_tool("tool_name", {"arg": "value"})
        await client.cleanup()
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self._exit_stack = AsyncExitStack()
        self.session: ClientSession | None = None

    async def connect(self) -> ClientSession:
        """Establish connection and initialize MCP session."""
        transport = await self._exit_stack.enter_async_context(
            streamablehttp_client(self.url)
        )
        read, write, _ = transport
        self.session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self.session.initialize()
        return self.session

    async def list_tools(self) -> list:
        """List all tools exposed by the connected MCP server."""
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")
        result = await self.session.list_tools()
        return result.tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the connected MCP server."""
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")
        result = await self.session.call_tool(tool_name, arguments)
        return result.content[0].text

    async def cleanup(self) -> None:
        """Close all connections and release resources."""
        await self._exit_stack.aclose()
        self.session = None

    async def __aenter__(self) -> "MCPHttpClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.cleanup()
```

### File 2: gateway/mcp_client/stdio_client.py

Implement class MCPStdioClient for local MCP servers via subprocess:

```python
"""Async MCP Stdio client for connecting to local MCP servers."""

from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPStdioClient:
    """MCP client that connects to servers via stdio transport.

    Usage:
        client = MCPStdioClient("python", ["my_server.py"])
        session = await client.connect()
        tools = await session.list_tools()
    """

    def __init__(self, command: str, args: list[str] | None = None) -> None:
        self.command = command
        self.args = args or []
        self._exit_stack = AsyncExitStack()
        self.session: ClientSession | None = None

    async def connect(self) -> ClientSession:
        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
        )
        transport = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read_stream, write_stream = transport
        self.session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self.session.initialize()
        return self.session

    async def list_tools(self) -> list:
        if not self.session:
            raise RuntimeError("Not connected.")
        result = await self.session.list_tools()
        return result.tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        if not self.session:
            raise RuntimeError("Not connected.")
        result = await self.session.call_tool(tool_name, arguments)
        return result.content[0].text

    async def cleanup(self) -> None:
        await self._exit_stack.aclose()
        self.session = None

    async def __aenter__(self) -> "MCPStdioClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.cleanup()
```

### File 3: gateway/mcp_client/manager.py

Implement MCPConnectionManager that manages multiple MCP server connections:

```python
"""Manager for multiple MCP server connections."""

from dataclasses import dataclass, field
from gateway.mcp_client.http_client import MCPHttpClient
from gateway.mcp_client.stdio_client import MCPStdioClient


@dataclass
class ServerConfig:
    name: str
    transport: str  # "http" or "stdio"
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)


class MCPConnectionManager:
    """Manages connections to multiple MCP servers.

    Usage:
        manager = MCPConnectionManager()
        manager.register("db", ServerConfig(name="db", transport="http",
                         url="http://localhost:8000/mcp"))
        await manager.connect_all()
        tools = await manager.list_all_tools()
        result = await manager.call_tool("db", "query", {"sql": "SELECT 1"})
        await manager.cleanup_all()
    """

    def __init__(self) -> None:
        self._servers: dict[str, ServerConfig] = {}
        self._clients: dict[str, MCPHttpClient | MCPStdioClient] = {}

    def register(self, name: str, config: ServerConfig) -> None:
        self._servers[name] = config

    async def connect_all(self) -> None:
        for name, cfg in self._servers.items():
            if cfg.transport == "http":
                client = MCPHttpClient(cfg.url)
            elif cfg.transport == "stdio":
                client = MCPStdioClient(cfg.command, cfg.args)
            else:
                raise ValueError(f"Unknown transport: {cfg.transport}")
            await client.connect()
            self._clients[name] = client

    async def list_all_tools(self) -> dict[str, list]:
        result = {}
        for name, client in self._clients.items():
            result[name] = await client.list_tools()
        return result

    async def call_tool(self, server_name: str, tool_name: str,
                        arguments: dict) -> str:
        client = self._clients.get(server_name)
        if not client:
            raise KeyError(f"Server '{server_name}' not connected.")
        return await client.call_tool(tool_name, arguments)

    async def cleanup_all(self) -> None:
        for client in self._clients.values():
            await client.cleanup()
        self._clients.clear()
```

### File 4: tests/test_mcp_client.py

Write pytest-asyncio tests that:
1. Create a simple MCP server in-process (add/subtract tools)
2. Test MCPHttpClient connect, list_tools, call_tool, cleanup
3. Test MCPStdioClient with subprocess server
4. Test MCPConnectionManager with 2 servers
5. Test error handling: connect without server, call without connect

Stop when: `uv run pytest tests/test_mcp_client.py -v` passes all tests.
```

### Acceptance Criteria
- [ ] `MCPHttpClient` connect/list/call/cleanup hoạt động
- [ ] `MCPStdioClient` connect/list/call/cleanup hoạt động
- [ ] `MCPConnectionManager` quản lý được 2+ servers
- [ ] Context manager (`async with`) hoạt động cho cả 2 client
- [ ] Tests pass 100%

---
## Phase 2 — LLM Provider Abstraction

### Dependencies: Phase 0

### Codex Goal Command

```
/goal Implement LLM provider abstraction layer in gateway/core/.
This allows switching between OpenAI, NVIDIA NIM, Anthropic, and Ollama
by changing one line in YAML config.

### File 1: gateway/core/models.py

Define all shared Pydantic models:

```python
"""Shared Pydantic models for the gateway."""

from enum import Enum
from pydantic import BaseModel, Field


class LLMProvider(str, Enum):
    OPENAI = "openai"
    NVIDIA_NIM = "nvidia-nim"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


class LLMConfig(BaseModel):
    """Configuration for an LLM provider."""
    provider: LLMProvider
    model_name: str
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 4096


class MCPServerConfig(BaseModel):
    """Configuration for an MCP server connection."""
    name: str
    transport: str = "http"
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    description: str = ""


class IntentConfig(BaseModel):
    """Configuration for an intent route."""
    name: str
    description: str
    mcp_server: str  # references MCPServerConfig.name
    system_prompt: str = ""


class WorkflowConfig(BaseModel):
    """Top-level workflow configuration (parsed from YAML)."""
    llm: LLMConfig
    mcp_servers: list[MCPServerConfig]
    intents: list[IntentConfig]
    gateway_port: int = 8001
    enable_tracing: bool = True
    human_in_the_loop_intents: list[str] = Field(default_factory=list)


class ToolSchema(BaseModel):
    """Normalized tool schema compatible with OpenAI function calling."""
    name: str
    description: str
    parameters: dict  # JSON Schema object
    server_name: str  # which MCP server owns this tool
```

### File 2: gateway/core/config.py

Parse YAML workflow config into WorkflowConfig:

```python
"""YAML configuration parser."""

import os
from pathlib import Path
import yaml
from gateway.core.models import WorkflowConfig


def load_config(config_path: str | Path) -> WorkflowConfig:
    """Load and validate workflow config from YAML file.

    Supports ${ENV_VAR} substitution in string values.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    # Substitute ${ENV_VAR} patterns
    for key, value in os.environ.items():
        raw = raw.replace(f"${{{key}}}", value)

    data = yaml.safe_load(raw)
    return WorkflowConfig(**data)
```

### File 3: gateway/core/llm_providers.py

Implement unified LLM client:

```python
"""Multi-provider LLM client abstraction."""

import os
from openai import AsyncOpenAI
from gateway.core.models import LLMConfig, LLMProvider


class LLMClient:
    """Unified async LLM client supporting multiple providers.

    All providers use OpenAI-compatible API via AsyncOpenAI,
    with different base_url for each provider.
    """

    PROVIDER_DEFAULTS = {
        LLMProvider.OPENAI: "https://api.openai.com/v1",
        LLMProvider.NVIDIA_NIM: "https://integrate.api.nvidia.com/v1",
        LLMProvider.ANTHROPIC: "https://api.anthropic.com/v1",
        LLMProvider.OLLAMA: "http://localhost:11434/v1",
    }

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        base_url = config.base_url or self.PROVIDER_DEFAULTS[config.provider]
        api_key = os.environ.get(config.api_key_env, "no-key-set")
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: type | None = None,
    ) -> dict:
        """Send chat completion request. Returns full response dict."""
        kwargs = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if response_format:
            kwargs["response_format"] = response_format

        response = await self._client.chat.completions.create(**kwargs)
        return response

    async def structured_output(
        self,
        messages: list[dict],
        response_model: type,
    ) -> object:
        """Get structured output parsed into a Pydantic model."""
        response = await self._client.beta.chat.completions.parse(
            model=self.config.model_name,
            messages=messages,
            response_format=response_model,
            temperature=self.config.temperature,
        )
        return response.choices[0].message.parsed
```

### File 4: tests/test_llm_providers.py

Write tests:
1. Test LLMConfig creation for each provider
2. Test load_config with sample YAML
3. Test LLMClient initialization (mock API calls)
4. Test env var substitution in config
5. Test WorkflowConfig validation with missing fields

Stop when: `uv run pytest tests/test_llm_providers.py -v` passes all tests.
```

### Acceptance Criteria
- [ ] `load_config()` parse YAML thanh `WorkflowConfig` dung
- [ ] `${ENV_VAR}` substitution hoat dong
- [ ] `LLMClient` khoi tao duoc cho ca 4 providers
- [ ] `ToolSchema` normalize MCP tools sang OpenAI format
- [ ] Tests pass 100%

---

## Phase 3 — LangGraph Router & Orchestrator

### Dependencies: Phase 1, Phase 2

### Codex Goal Command

```
/goal Implement the LangGraph-powered intent router and multi-MCP orchestrator.
This is the brain of the gateway - it classifies user intent and routes to
the correct agent/MCP server.

### File 1: gateway/core/state.py

Define the LangGraph state schema:

```python
"""LangGraph state schema for the gateway workflow."""

from typing import Annotated, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class GatewayState(TypedDict):
    """State flowing through the gateway workflow graph.

    Fields:
    - messages: conversation history (auto-appended by add_messages)
    - intent: classified intent name (e.g., "database_query", "refund")
    - active_server: which MCP server to use
    - tool_results: raw results from MCP tool calls
    - response: final formatted response to user
    - metadata: extra data (invoice_id, customer_name, etc.)
    """
    messages: Annotated[list, add_messages]
    intent: str
    active_server: str
    tool_results: list[dict[str, Any]]
    response: str
    metadata: dict[str, Any]
```

### File 2: gateway/core/router.py

Implement the intent classifier as a LangGraph node:

```python
"""LangGraph intent classifier node."""

from pydantic import BaseModel, Field
from typing import Literal
from langgraph.types import Command
from gateway.core.llm_providers import LLMClient
from gateway.core.models import IntentConfig
from gateway.core.state import GatewayState


def build_intent_model(intents: list[IntentConfig]) -> type:
    """Dynamically build a Pydantic model with Literal intent types.

    Example: if intents = [IntentConfig(name="QNA"), IntentConfig(name="REFUND")]
    Returns a model with: intent: Literal["QNA", "REFUND", "UNKNOWN"]
    """
    intent_names = tuple([i.name for i in intents] + ["UNKNOWN"])
    IntentLiteral = Literal[intent_names]  # type: ignore

    class UserIntent(BaseModel):
        intent: IntentLiteral = Field(
            description="The classified user intent"
        )
        confidence: float = Field(
            ge=0.0, le=1.0,
            description="Confidence score of the classification"
        )

    return UserIntent


def create_intent_classifier(
    llm_client: LLMClient,
    intents: list[IntentConfig],
    intent_to_node: dict[str, str],
):
    """Create an intent classifier node function for LangGraph.

    Args:
        llm_client: LLM client for classification
        intents: list of intent configurations
        intent_to_node: mapping from intent name to graph node name

    Returns:
        Async function usable as a LangGraph node
    """
    IntentModel = build_intent_model(intents)
    intent_descriptions = '\n'.join(
        f"- {i.name}: {i.description}" for i in intents
    )
    system_prompt = f"""You are an intent classifier. Classify the user message
into one of these intents:
{intent_descriptions}
- UNKNOWN: if the message does not match any intent

Return ONLY a JSON object with "intent" and "confidence" fields."""

    async def intent_classifier(state: GatewayState) -> Command:
        messages = [
            {"role": "system", "content": system_prompt},
        ] + state["messages"]

        result = await llm_client.structured_output(messages, IntentModel)
        target_node = intent_to_node.get(result.intent, "unknown_handler")

        return Command(
            goto=target_node,
            update={
                "intent": result.intent,
                "metadata": {
                    **state.get("metadata", {}),
                    "intent_confidence": result.confidence,
                },
            },
        )

    return intent_classifier
```

### File 3: gateway/core/orchestrator.py

Main orchestrator that builds and runs the full workflow:

```python
"""Multi-MCP orchestrator - builds and executes LangGraph workflow."""

import json
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt

from gateway.core.state import GatewayState
from gateway.core.router import create_intent_classifier
from gateway.core.llm_providers import LLMClient
from gateway.core.models import WorkflowConfig, IntentConfig
from gateway.mcp_client.manager import MCPConnectionManager, ServerConfig


class GatewayOrchestrator:
    """Builds and runs the complete agent workflow.

    Architecture:
    START -> intent_classifier -> [agent_node_per_intent] -> compile_response -> END
                               -> unknown_handler (interrupt) -> END
    """

    def __init__(self, config: WorkflowConfig) -> None:
        self.config = config
        self.llm_client = LLMClient(config.llm)
        self.mcp_manager = MCPConnectionManager()
        self._workflow = None

    async def setup(self) -> None:
        """Connect to all MCP servers and build the workflow graph."""
        for server_cfg in self.config.mcp_servers:
            self.mcp_manager.register(
                server_cfg.name,
                ServerConfig(
                    name=server_cfg.name,
                    transport=server_cfg.transport,
                    url=server_cfg.url,
                    command=server_cfg.command,
                    args=server_cfg.args,
                ),
            )
        await self.mcp_manager.connect_all()
        self._workflow = await self._build_workflow()

    async def _build_workflow(self) -> object:
        """Build the LangGraph StateGraph."""
        graph = StateGraph(GatewayState)

        # Map intent -> node name
        intent_to_node = {}
        for intent_cfg in self.config.intents:
            node_name = f"agent_{intent_cfg.name.lower()}"
            intent_to_node[intent_cfg.name] = node_name

            # Create agent node for this intent
            agent_fn = self._create_agent_node(intent_cfg)
            graph.add_node(node_name, agent_fn)
            graph.add_edge(node_name, "compile_response")

        # Unknown handler with human-in-the-loop
        graph.add_node("unknown_handler", self._unknown_handler)
        graph.add_edge("unknown_handler", "compile_response")
        intent_to_node["UNKNOWN"] = "unknown_handler"

        # Intent classifier
        classifier = create_intent_classifier(
            self.llm_client, self.config.intents, intent_to_node
        )
        graph.add_node("intent_classifier", classifier)
        graph.set_entry_point("intent_classifier")

        # Compile response
        graph.add_node("compile_response", self._compile_response)
        graph.add_edge("compile_response", END)

        memory = InMemorySaver()
        return graph.compile(checkpointer=memory)

    def _create_agent_node(self, intent_cfg: IntentConfig):
        """Create an agent node that uses MCP tools for a specific intent."""
        async def agent_node(state: GatewayState) -> dict:
            server_name = intent_cfg.mcp_server
            tools = await self.mcp_manager.list_all_tools()
            server_tools = tools.get(server_name, [])

            # Convert MCP tools to OpenAI function-calling format
            openai_tools = []
            for tool in server_tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                })

            messages = [
                {"role": "system", "content": intent_cfg.system_prompt
                 or f"You are a helpful agent for {intent_cfg.name} tasks."},
            ] + state["messages"]

            response = await self.llm_client.chat(messages, tools=openai_tools)
            choice = response.choices[0]
            tool_results = []

            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    args = json.loads(tc.function.arguments)
                    result = await self.mcp_manager.call_tool(
                        server_name, tc.function.name, args
                    )
                    tool_results.append({
                        "tool": tc.function.name,
                        "result": result,
                    })

            return {
                "active_server": server_name,
                "tool_results": tool_results,
                "response": choice.message.content or "",
            }

        return agent_node

    async def _unknown_handler(self, state: GatewayState) -> dict:
        """Handle unknown intents with human-in-the-loop."""
        if self.config.human_in_the_loop_intents:
            answer = interrupt("I do not understand. Please rephrase.")
            return {"response": str(answer)}
        return {"response": "I am not sure how to help with that."}

    async def _compile_response(self, state: GatewayState) -> dict:
        """Format final response from tool results."""
        if state.get("tool_results"):
            parts = []
            for tr in state["tool_results"]:
                parts.append(f"[{tr['tool']}]: {tr['result']}")
            return {"response": "\n".join(parts)}
        return {}

    async def run(self, user_message: str, thread_id: str = "default") -> str:
        """Run the workflow with a user message."""
        if not self._workflow:
            raise RuntimeError("Call setup() first.")
        result = self._workflow.invoke(
            {
                "messages": [{"role": "user", "content": user_message}],
                "intent": "",
                "active_server": "",
                "tool_results": [],
                "response": "",
                "metadata": {},
            },
            {"configurable": {"thread_id": thread_id}},
        )
        return result.get("response", "No response generated.")

    async def teardown(self) -> None:
        """Cleanup all connections."""
        await self.mcp_manager.cleanup_all()
```

### Tests: tests/test_router.py + tests/test_orchestrator.py

Write comprehensive tests:
- Test dynamic Pydantic intent model creation
- Test intent classifier with mocked LLM
- Test full orchestrator setup/run/teardown with a mock MCP server
- Test unknown intent handling
- Test thread_id memory across multiple calls

Stop when: `uv run pytest tests/test_router.py tests/test_orchestrator.py -v`
passes all tests.
```

### Acceptance Criteria
- [ ] Intent classifier tao dynamic Pydantic model tu config
- [ ] Router tra `Command(goto=...)` dung node
- [ ] Orchestrator build graph: START -> classifier -> agents -> compile -> END
- [ ] MCP tool calls duoc convert sang OpenAI format va goi thanh cong
- [ ] Unknown intent trigger interrupt hoac fallback message
- [ ] Thread memory hoat dong (cung thread_id nho context)
- [ ] Tests pass 100%

---
## Phase 4 — Example MCP Servers

### Dependencies: Phase 1

### Codex Goal Command

```
/goal Build 3 example MCP servers + 1 cookiecutter template.
Each server uses low-level MCP SDK with HTTP transport (Starlette + Uvicorn).

### Server 1: servers/database/server.py

SQLite MCP server with 2 tools: query_database, list_tables.
Pattern: Low-level MCP SDK (not FastMCP).

```python
"""SQLite Database MCP Server - exposes SQL query tools via MCP HTTP."""

import json
import sqlite3
import os
from typing import Any
from mcp.server.lowlevel import Server
from mcp import types
from starlette.applications import Starlette
from starlette.routing import Mount
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
import uvicorn

DB_PATH = os.environ.get("DB_PATH", "example.db")
server = Server("database-mcp")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="query_database",
            description="Execute a read-only SQL query and return results as JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SQL SELECT query to execute"
                    },
                },
                "required": ["sql"],
            },
        ),
        types.Tool(
            name="list_tables",
            description="List all tables in the database.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any] | None):
    args = arguments or {}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if name == "query_database":
            sql = args.get("sql", "")
            if not sql.strip().upper().startswith("SELECT"):
                return [types.TextContent(
                    type="text",
                    text="Error: Only SELECT queries are allowed."
                )]
            cursor = conn.execute(sql)
            rows = [dict(row) for row in cursor.fetchall()]
            return [types.TextContent(
                type="text", text=json.dumps(rows, indent=2)
            )]
        elif name == "list_tables":
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row["name"] for row in cursor.fetchall()]
            return [types.TextContent(
                type="text", text=json.dumps(tables)
            )]
        else:
            raise ValueError(f"Unknown tool: {name}")
    finally:
        conn.close()

# HTTP transport setup
session_manager = StreamableHTTPSessionManager(
    app=server, event_store=None, json_response=True, stateless=True,
)

async def handle_mcp(scope, receive, send):
    await session_manager.handle_request(scope, receive, send)

app = Starlette(routes=[Mount("/mcp", app=handle_mcp)])

if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)
```

Also create servers/database/db_helper.py with a function to create a
sample SQLite database for testing (3 tables: users, products, orders).

### Server 2: servers/rest_api/server.py

Generic REST-to-MCP bridge. Expose tool: call_api
Takes method, url, headers, body and makes HTTP request.
Only allow GET and POST. Return response body as text.
Use httpx for async HTTP calls.

### Server 3: servers/filesystem/server.py

File operations MCP server. Tools:
- list_directory: list files in a directory (with safety: only under allowed_root)
- read_file: read text file content (max 100KB)
- search_files: grep-like search in directory

### Server 4: servers/template/

Create a cookiecutter template with:
- cookiecutter.json: project_name, tool_names (comma-separated), port
- {{cookiecutter.project_name}}/server.py: skeleton with list_tools + call_tool
- {{cookiecutter.project_name}}/pyproject.toml
- {{cookiecutter.project_name}}/README.md

### Tests: tests/test_servers/

- test_database_server.py: start server, connect client, list/call tools
- test_rest_api_server.py: mock HTTP endpoint, test call_api tool

Each server must have its own pyproject.toml with:
  [project.scripts]
  serve = "server:main"

Stop when: all 3 servers start independently and respond to MCP client
tool list and tool call requests. `uv run pytest tests/test_servers/ -v` passes.
```

### Acceptance Criteria
- [ ] Database server: query_database tra JSON rows, list_tables hoat dong
- [ ] REST API server: call_api voi GET/POST thanh cong
- [ ] Filesystem server: list/read/search trong allowed_root
- [ ] Cookiecutter template tao duoc server moi bang `cookiecutter servers/template/`
- [ ] Tat ca server chay HTTP tren `/mcp` endpoint
- [ ] SELECT-only enforcement cho database server
- [ ] Tests pass

---

## Phase 5 — Agent Skills & OpenClaw Integration

### Dependencies: Phase 1, Phase 4

### Codex Goal Command

```
/goal Implement agent skill system compatible with OpenClaw.
Auto-generate SKILL.md files from MCP server tool schemas.

### File 1: gateway/skills/generator.py

```python
"""Auto-generate OpenClaw-compatible SKILL.md from MCP server schemas."""

from pathlib import Path
from gateway.mcp_client.http_client import MCPHttpClient


async def generate_skill_md(
    server_url: str,
    skill_name: str,
    skill_description: str,
    gateway_endpoint: str = "http://localhost:8001/generate",
    output_dir: Path | None = None,
) -> str:
    """Connect to MCP server, read tool schemas, generate SKILL.md.

    The generated SKILL.md instructs OpenClaw agent to call the
    gateway HTTP endpoint with the user query.

    Args:
        server_url: MCP server URL (e.g., http://localhost:8000/mcp)
        skill_name: Name for the skill
        skill_description: Short description
        gateway_endpoint: Gateway generate endpoint
        output_dir: Where to write SKILL.md (optional)

    Returns:
        SKILL.md content as string
    """
    async with MCPHttpClient(server_url) as client:
        tools = await client.list_tools()

    tool_descriptions = '\n'.join(
        f"- **{t.name}**: {t.description}" for t in tools
    )

    content = f"""---
name: {skill_name}
description: {skill_description}
---

# {skill_name}

## Available Capabilities
{tool_descriptions}

## How to Use
Replace <query> with the exact question from the user/agent.
Do not remove or modify any information from the original query.

```bash
curl -X POST {gateway_endpoint} \\
  -H "Content-Type: application/json" \\
  -d '{{"input_message": "<query>"}}'
```

## Important Rules
- Always pass the COMPLETE user question without modification
- Do not invent data - all information comes from the backend tools
- If the response contains an error, relay it to the user clearly
"""

    if output_dir:
        skill_dir = output_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    return content
```

### File 2: gateway/skills/openclaw_setup.py

Helper to auto-configure OpenClaw with the gateway:
- Generate SOUL.md for an agent
- Generate SKILL.md for each MCP server
- Print instructions for openclaw.json provider config

### CLI command in gateway/cli.py:

Add subcommand: `amcpg skills generate --server-url ... --output-dir ...`
Add subcommand: `amcpg skills openclaw-setup --config workflow.yaml`

Stop when: `amcpg skills generate --server-url http://localhost:8000/mcp
--output-dir ./skills-output` creates a valid SKILL.md file, and
the SKILL.md format matches OpenClaw expected pattern.
```

### Acceptance Criteria
- [ ] `generate_skill_md()` ket noi MCP server va tao SKILL.md dung format
- [ ] SKILL.md chua tool descriptions tu MCP server
- [ ] CLI command `amcpg skills generate` hoat dong
- [ ] SKILL.md tuong thich OpenClaw agent skill pattern

---

## Phase 6 — Observability & Tracing

### Dependencies: Phase 3

### Codex Goal Command

```
/goal Add OpenTelemetry tracing and Phoenix integration to the gateway.
Every tool call, LLM call, and routing decision must produce a trace span.

### File: gateway/observability/tracer.py

```python
"""OpenTelemetry + Phoenix observability for the gateway."""

import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)


def setup_tracing(service_name: str = "agentic-mcp-gateway") -> trace.Tracer:
    """Initialize OpenTelemetry tracing with OTLP exporter.

    If OTEL_EXPORTER_OTLP_ENDPOINT is set, exports to that endpoint.
    Otherwise exports to Phoenix default (localhost:6006).
    """
    provider = TracerProvider()
    endpoint = os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:6006"
    )
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


_tracer: trace.Tracer | None = None

def get_tracer() -> trace.Tracer:
    global _tracer
    if _tracer is None:
        _tracer = setup_tracing()
    return _tracer


def trace_tool_call(server_name: str, tool_name: str, arguments: dict):
    """Create a span for an MCP tool call."""
    tracer = get_tracer()
    span = tracer.start_span(f"mcp.tool.{tool_name}")
    span.set_attribute("mcp.server", server_name)
    span.set_attribute("mcp.tool", tool_name)
    span.set_attribute("mcp.arguments", str(arguments))
    return span


def trace_llm_call(provider: str, model: str, token_count: int = 0):
    """Create a span for an LLM call."""
    tracer = get_tracer()
    span = tracer.start_span(f"llm.chat.{provider}")
    span.set_attribute("llm.provider", provider)
    span.set_attribute("llm.model", model)
    span.set_attribute("llm.tokens", token_count)
    return span


def trace_router_decision(intent: str, confidence: float):
    """Create a span for a routing decision."""
    tracer = get_tracer()
    span = tracer.start_span("router.classify")
    span.set_attribute("router.intent", intent)
    span.set_attribute("router.confidence", confidence)
    return span
```

Integrate tracing into:
- gateway/mcp_client/http_client.py: wrap call_tool with trace_tool_call
- gateway/core/llm_providers.py: wrap chat() with trace_llm_call
- gateway/core/router.py: wrap classifier with trace_router_decision

Add to docker-compose.yml:
  phoenix:
    image: arizephoenix/phoenix:latest
    ports:
      - "6006:6006"

Stop when: running the gateway with Phoenix shows trace spans for
tool calls, LLM calls, and routing decisions in the Phoenix UI at
http://localhost:6006.
```

### Acceptance Criteria
- [ ] `setup_tracing()` khoi tao OTel provider
- [ ] Tool call, LLM call, router decision deu tao spans
- [ ] Phoenix UI hien thi traces
- [ ] Tracing co the tat qua `enable_tracing: false` trong config

---
## Phase 7 — Full Demo Examples

### Dependencies: Phase 3, Phase 4

### Codex Goal Command

```
/goal Create 3 complete demo examples with workflow.yaml configs.

### Example 1: examples/music-store/

Full Chinook DB demo replicating the NVIDIA Agentic AI Bootcamp pattern.

Files:
- examples/music-store/workflow.yaml
- examples/music-store/README.md
- examples/music-store/data/chinook.db (download script)
- examples/music-store/skills/music-store-assistant/SKILL.md

workflow.yaml:
```yaml
llm:
  provider: openai
  model_name: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
  temperature: 0.0
  max_tokens: 4096

mcp_servers:
  - name: music-db
    transport: http
    url: http://localhost:8000/mcp
    description: "Chinook music store database"

intents:
  - name: QNA
    description: "Questions about artists, albums, tracks, genres, customers"
    mcp_server: music-db
    system_prompt: |
      You are a music store assistant. Use the query_database tool
      to answer questions about the Chinook music database.
      Tables: Artist, Album, Track, Genre, Invoice, InvoiceLine, Customer.
      Only use SELECT queries. Do not invent data.

  - name: REFUND
    description: "Customer requests to refund purchases"
    mcp_server: music-db
    system_prompt: |
      You are a refund processing agent. Use tools to look up invoices
      and process refunds. Always confirm with the customer before refunding.

human_in_the_loop_intents:
  - REFUND

gateway_port: 8001
enable_tracing: true
```

README.md with:
- Architecture diagram (Mermaid)
- Quick start (3 commands)
- Example queries
- Screenshots placeholder

### Example 2: examples/devops-assistant/

DevOps helper that queries Docker containers and K8s status.

workflow.yaml with:
- rest-api MCP server pointing to Docker API socket
- Intents: CONTAINER_STATUS, LOG_QUERY, UNKNOWN

### Example 3: examples/research-agent/

Research helper that searches web and summarizes.

workflow.yaml with:
- rest-api MCP server pointing to a search API
- filesystem MCP server for saving notes
- Intents: SEARCH, SAVE_NOTE, SUMMARIZE

Stop when: `amcpg serve --config examples/music-store/workflow.yaml`
starts the gateway and responds to test queries correctly.
```

### Acceptance Criteria
- [ ] Music-store example chay end-to-end voi Chinook DB
- [ ] DevOps example co config hop le
- [ ] Research example ket noi 2 MCP servers
- [ ] Moi example co README rieng

---

## Phase 8 — Documentation & CI/CD

### Dependencies: Phase 0-7

### Codex Goal Command

```
/goal Create comprehensive documentation, CI/CD pipelines, and Docker support.

### README.md (root)

Must include:
1. Project name + logo placeholder + badges (PyPI, CI, License, Stars)
2. One-line description: "Connect any LLM to any MCP server through one gateway"
3. Key features list (6 items with emoji)
4. Architecture diagram (Mermaid code block)
5. Quick Start (5 steps: clone, install, config, start, query)
6. Configuration guide (YAML example)
7. Supported LLM providers table
8. Example MCP servers table
9. Creating custom MCP server (link to docs/)
10. OpenClaw integration section
11. Observability section (Phoenix screenshot placeholder)
12. Contributing section (link to CONTRIBUTING.md)
13. License (Apache-2.0)
14. Star History badge placeholder

### docs/getting-started.md
- Prerequisites (Python 3.12+, uv)
- Installation (pip, uv, Docker)
- First workflow in 5 minutes
- Understanding workflow.yaml

### docs/architecture.md
- System overview
- Component diagram
- Data flow: request -> classify -> route -> tool call -> response
- Extension points

### docs/create-mcp-server.md
- Using the cookiecutter template
- Implementing list_tools and call_tool
- Testing your server
- Registering in workflow.yaml

### CONTRIBUTING.md
- Code of Conduct reference
- Development setup
- Running tests
- PR process
- Code style guide

### .github/workflows/ci.yml
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-extras
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest --cov=gateway --cov-report=xml
      - uses: codecov/codecov-action@v4
```

### .github/workflows/release.yml
PyPI publish on tag push using trusted publishers.

### docker-compose.yml
```yaml
services:
  gateway:
    build: .
    ports:
      - "8001:8001"
    environment:
      - OPENAI_API_KEY
      - GATEWAY_CONFIG=/app/workflow.yaml
    volumes:
      - ./workflow.yaml:/app/workflow.yaml
    depends_on:
      - phoenix

  database-mcp:
    build: ./servers/database
    ports:
      - "8000:8000"
    environment:
      - DB_PATH=/data/example.db
    volumes:
      - ./examples/music-store/data:/data

  phoenix:
    image: arizephoenix/phoenix:latest
    ports:
      - "6006:6006"
```

### Dockerfile
Multi-stage build: uv install -> copy source -> expose port -> CMD amcpg serve

Stop when: `docker compose up` starts all 3 services, CI workflow YAML
is valid, and all markdown files render correctly.
```

### Acceptance Criteria
- [ ] README.md co du 14 sections
- [ ] `docker compose up` chay gateway + MCP server + Phoenix
- [ ] CI workflow chay lint + test + coverage
- [ ] Docs render dung tren GitHub

---

## Phase 9 — Polish & GitHub Stars Strategy

### Dependencies: Phase 8

### Codex Goal Command

```
/goal Polish the repository for maximum GitHub appeal and community adoption.

### Tasks:

1. Create examples/demo.gif placeholder and script to record demo:
   - Install vhs (charmbracelet/vhs)
   - Script: start gateway -> send 3 queries -> show responses
   - Convert to GIF for README

2. Add GitHub repository files:
   - .github/ISSUE_TEMPLATE/bug_report.yml
   - .github/ISSUE_TEMPLATE/feature_request.yml
   - .github/PULL_REQUEST_TEMPLATE.md
   - .github/FUNDING.yml (GitHub Sponsors placeholder)

3. Create social media announcement templates:
   - docs/announcements/reddit-post.md (for r/LocalLLaMA, r/MachineLearning)
   - docs/announcements/hackernews-post.md
   - docs/announcements/twitter-thread.md
   - docs/announcements/devto-article.md

4. Awesome-list submission checklist:
   - awesome-mcp (submit PR)
   - awesome-ai-agents
   - awesome-langgraph

5. SEO optimization:
   - GitHub topics: agentic-ai, mcp, langgraph, llm, openai, tool-calling,
     agent-framework, multi-agent, observability
   - GitHub description: "Connect any LLM to any MCP tool server.
     Multi-agent gateway with LangGraph routing, OpenTelemetry tracing,
     and OpenClaw integration."

6. Add CHANGELOG.md with v0.1.0 release notes

7. Create GitHub Release v0.1.0 with:
   - Release notes
   - Binary/wheel attachment
   - Installation instructions

Stop when: repository has all templates, topics are set, and README
renders with architecture diagram and feature list.
```

### Checklist tang Stars

- [ ] README co demo GIF o dau trang
- [ ] GitHub Topics da set (8-10 topics trending)
- [ ] Issue/PR templates tao xong
- [ ] Social media posts drafted
- [ ] Awesome-list targets identified
- [ ] CHANGELOG.md v0.1.0
- [ ] First GitHub Release published

---

## Phase 10 — Apply OpenAI Codex for OSS

### Dependencies: Phase 9, >= 100 GitHub stars

### Application Strategy

Khi repo dat **>= 100 stars** (ly tuong >= 1,000), apply tai:
https://openai.com/es-ES/form/codex-for-oss/

### Form Fields — Goi y noi dung dien

**Project URL:**
```
https://github.com/sinhpham/agentic-mcp-gateway
```

**Describe your project:**
```
agentic-mcp-gateway is an open-source Python framework that enables
developers to connect any LLM (OpenAI, NVIDIA NIM, Anthropic, Ollama)
to multiple MCP (Model Context Protocol) tool servers through a single
LangGraph-powered gateway. It provides built-in intent routing,
OpenTelemetry observability, and OpenClaw-compatible skill export.
The project bridges the growing MCP ecosystem (60k+ stars on official
servers) with production-grade agent orchestration.
```

**How will you use Codex?**
```
1. Automated PR review and code quality checks for community contributions
2. Implementing new MCP server templates based on community requests
3. CI/CD automation: generating tests, fixing linting issues, updating docs
4. Triaging and responding to GitHub issues
5. Building integration tests across different LLM providers
6. The project itself was built entirely using Codex /goal feature,
   demonstrating Codex capability for complex multi-file projects
```

**How will you use API credits?**
```
1. Integration testing across OpenAI models (GPT-4o, GPT-4o-mini)
2. Automated benchmarking of routing accuracy across providers
3. Powering the default demo instance for new users
4. CI pipeline: automated test generation and code review
5. Documentation generation and translation
```

**Impact statement:**
```
MCP is rapidly becoming the "USB-C of AI tooling" with 60k+ stars.
Our framework lowers the barrier to building multi-MCP agent systems
from days to minutes. We provide cookiecutter templates, YAML-first
config, and auto-generated OpenClaw skills - enabling developers
to focus on business logic instead of infrastructure.
```

### Metrics to Track

| Metric | Target (30 days) | Target (90 days) |
|--------|------------------|-------------------|
| GitHub Stars | 500+ | 2,000+ |
| Forks | 50+ | 200+ |
| Contributors | 10+ | 30+ |
| PyPI Downloads | 1,000+ | 10,000+ |
| Issues (active) | 20+ | 50+ |
| Discord/Discussions | 100 members | 500 members |

---

## Tong ket — Thu tu thuc hien

```
Phase 0 (Scaffolding)        <-- BAT DAU TU DAY
    |
    +-- Phase 1 (MCP Client) <-- song song voi Phase 2
    |       |
    |       +-- Phase 4 (Example Servers)
    |               |
    |               +-- Phase 5 (Skills/OpenClaw)
    |
    +-- Phase 2 (LLM Providers) <-- song song voi Phase 1
    |       |
    |       +-- Phase 3 (Router/Orchestrator)
    |               |
    |               +-- Phase 6 (Observability)
    |
    +-- Phase 7 (Demo Examples) <-- sau Phase 3 + 4
            |
            +-- Phase 8 (Docs/CI) <-- sau Phase 7
                    |
                    +-- Phase 9 (Polish) <-- sau Phase 8
                            |
                            +-- Phase 10 (Apply OSS) <-- khi du stars
```

### Uoc tinh thoi gian voi Codex /goal

| Phase | Thoi gian uoc tinh | Codex Mode |
|-------|-------------------|------------|
| 0 | 15-30 phut | full-auto |
| 1 | 30-45 phut | full-auto |
| 2 | 30-45 phut | full-auto |
| 3 | 45-60 phut | suggest (review router logic) |
| 4 | 45-60 phut | full-auto |
| 5 | 20-30 phut | full-auto |
| 6 | 30-45 phut | full-auto |
| 7 | 30-45 phut | suggest (review examples) |
| 8 | 30-45 phut | full-auto |
| 9 | 20-30 phut | manual + full-auto |
| **Tong** | **~5-7 gio** | |

---

> **Luu y cuoi:** Sau moi Phase, commit code va push len GitHub.
> Moi Phase nen la 1 PR rieng de de track progress.
> Dung conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `ci:`.

---

## Phu luc — Sample workflow.yaml de test nhanh

Tao file `workflow.yaml` o root de test gateway nhanh:

```yaml
# workflow.yaml - Quick start config
llm:
  provider: openai
  model_name: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
  temperature: 0.0
  max_tokens: 4096

mcp_servers:
  - name: demo-db
    transport: http
    url: http://localhost:8000/mcp
    description: "Demo SQLite database with users, products, orders"

intents:
  - name: QUERY
    description: "Database queries about users, products, and orders"
    mcp_server: demo-db
    system_prompt: |
      You are a database assistant. Use query_database tool to answer
      questions. Tables: users (id, name, email), products (id, name,
      price), orders (id, user_id, product_id, quantity, date).
      Only SELECT queries. Do not invent data.

  - name: SCHEMA
    description: "Questions about database structure and table schemas"
    mcp_server: demo-db
    system_prompt: |
      You are a schema assistant. Use list_tables tool to show
      available tables and their structure.

gateway_port: 8001
enable_tracing: true
human_in_the_loop_intents: []
```

### Quick test commands

```bash
# Terminal 1: Start MCP server
cd servers/database
DB_PATH=../../examples/music-store/data/chinook.db uv run python server.py

# Terminal 2: Start gateway
amcpg serve --config workflow.yaml

# Terminal 3: Test query
curl -X POST http://localhost:8001/generate \
  -H "Content-Type: application/json" \
  -d '{"input_message": "How many tracks are in the database?"}'
```