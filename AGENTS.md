# agentic-mcp-gateway

## Project Overview
An open-source Python framework for building multi-MCP agent workflows.
Connect any LLM (OpenAI, NVIDIA NIM, Anthropic, Ollama) to any number of
MCP tool servers through a single LangGraph-powered gateway with built-in
intent routing, observability, and OpenClaw-compatible skill export.

## Architecture
```
User Request
    |
    v
+---------------------+
|  Intent Classifier   | <- Pydantic structured output
|  (LangGraph node)    |
+---------+-----------+
          |
    +-----+----------+
    v     v          v
[Agent A] [Agent B] [Agent C]
    |        |          |
    v        v          v
[MCP 1]  [MCP 2]   [MCP N]
(DB)     (REST)    (Custom)
    |        |          |
    +--------+----------+
             v
   +------------------+
   | Compile Response  |
   | + OTel Trace      |
   +------------------+
```

## Tech Stack
- Python 3.12+, package manager: uv
- MCP SDK: mcp[cli] (low-level Server + ClientSession)
- Orchestration: langgraph >= 0.2
- Structured output: pydantic >= 2.0
- LLM clients: openai (AsyncOpenAI), anthropic
- HTTP transport: starlette + uvicorn
- Config: pyyaml + pydantic-settings
- Observability: opentelemetry-api/sdk, arize-phoenix
- Testing: pytest + pytest-asyncio, coverage > 80%
- Linting: ruff, Type checking: mypy

## Code Style
- Type hints required on ALL functions (Google-style docstrings)
- Indentation: 4 spaces, max line: 100 chars
- async/await for ALL I/O, Pydantic BaseModel for configs
- TypedDict for LangGraph state schemas
- No hardcoded API keys - environment variables only
- Apache-2.0 license header on every file
- All imports sorted with ruff isort
- Every module MUST have a module-level docstring

## File Naming
- Python: snake_case.py
- Config: kebab-case.yaml
- Docs: kebab-case.md
- Directories: snake_case/

## Testing Rules
- Test files: tests/test_<module>.py
- Coverage target: > 80%
- All MCP servers must have integration tests
- Use pytest fixtures for MCP client/server setup
- Mock LLM calls in unit tests, use real calls only in integration tests

## Architecture Rules
- All MCP servers MUST implement @server.list_tools() and @server.call_tool()
- All MCP servers MUST support HTTP transport via Starlette + Uvicorn
- LLM provider MUST be swappable via YAML config without code changes
- No hardcoded API keys - use environment variables
- All tool calls MUST be traced with OpenTelemetry spans
- State schema MUST use Annotated[list, add_messages] for conversation history
- Intent classifier MUST return Pydantic model with Literal types
- Human-in-the-loop via LangGraph interrupt() for destructive operations

## Environment Variables
- OPENAI_API_KEY: OpenAI API key
- NVIDIA_API_KEY: NVIDIA NIM API key
- ANTHROPIC_API_KEY: Anthropic API key
- OLLAMA_BASE_URL: Ollama endpoint (default http://localhost:11434/v1)
- GATEWAY_CONFIG: path to workflow YAML (default ./workflow.yaml)
- OTEL_EXPORTER_OTLP_ENDPOINT: OTel collector endpoint
- PHOENIX_PORT: Phoenix UI port (default 6006)

## Dependencies (pyproject.toml)
```toml
[project]
name = "agentic-mcp-gateway"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=1.0",
    "langgraph>=0.2",
    "langchain-core>=0.3",
    "openai>=1.50",
    "anthropic>=0.30",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "starlette>=0.40",
    "uvicorn>=0.30",
    "httpx>=0.27",
    "opentelemetry-api>=1.25",
    "opentelemetry-sdk>=1.25",
    "opentelemetry-exporter-otlp>=1.25",
    "arize-phoenix>=4.0",
    "rich>=13.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.5", "mypy>=1.10"]

[project.scripts]
amcpg = "gateway.cli:main"
```