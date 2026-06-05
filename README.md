# agentic-mcp-gateway
<!-- Topics: agentic-ai, mcp, langgraph, llm, openai, tool-calling, agent-framework, multi-agent -->
[![CI](https://github.com/sinh/agentic-mcp-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/sinh/agentic-mcp-gateway/actions)
[![PyPI](https://img.shields.io/pypi/v/agentic-mcp-gateway)](https://pypi.org/project/agentic-mcp-gateway/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Stars](https://img.shields.io/github/stars/sinh/agentic-mcp-gateway?style=social)](https://github.com/sinh/agentic-mcp-gateway)

Connect any LLM to any MCP server through one gateway

## Features

- **Multi-LLM**: Seamlessly switch between OpenAI, Anthropic, NVIDIA NIM, and Ollama.
- **Multi-MCP**: Connect and orchestrate multiple Model Context Protocol (MCP) servers.
- **LangGraph Integration**: Built-in intent routing and agent orchestration.
- **Skills Export**: OpenClaw-compatible skill export for agent tooling.
- **OTel Observability**: Native OpenTelemetry tracing and integration with Arize Phoenix.
- **YAML-first Configuration**: Define workflows and connections cleanly with declarative YAML.

## Architecture

```mermaid
flowchart TD
    User([User Request]) --> Gateway[LangGraph Intent Router]
    
    subgraph Gateway System
        Gateway -->|Route| AgentA[Agent A]
        Gateway -->|Route| AgentB[Agent B]
        Gateway -->|Route| AgentC[Agent C]
    end
    
    subgraph MCP Ecosystem
        AgentA --> MCPServer1[MCP Server 1]
        AgentB --> MCPServer2[MCP Server 2]
        AgentC --> MCPServerN[MCP Server N]
    end
    
    MCPServer1 --> ResponseCompiler[Compile Response]
    MCPServer2 --> ResponseCompiler
    MCPServerN --> ResponseCompiler
    
    ResponseCompiler -->|With OTel Trace| User
```

## Quick Start

Follow these 5 steps to get up and running:

1. **Install uv** (the recommended Python package manager):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Install the gateway**:
   ```bash
   uv pip install agentic-mcp-gateway
   ```

3. **Start an MCP server** (e.g., local filesystem):
   ```bash
   mcp-server-filesystem /path/to/files --port 8000
   ```

4. **Start the gateway**:
   ```bash
   amcpg start --config workflow.yaml
   ```

5. **Test it**:
   ```bash
   curl -X POST http://localhost:8080/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"messages": [{"role": "user", "content": "List files in my directory"}]}'
   ```

## Configuration Guide

The gateway is configured via a simple YAML file (`workflow.yaml`). Here is a basic example:

```yaml
llm:
  provider: openai
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}

agents:
  - name: FileAgent
    description: Handles file system operations
    mcp_servers:
      - name: local-fs
        url: http://localhost:8000

observability:
  otel_endpoint: ${OTEL_EXPORTER_OTLP_ENDPOINT}
```

## LLM Providers

| Provider | Supported Models | Required Environment Variable |
| --- | --- | --- |
| **OpenAI** | `gpt-4o`, `gpt-4-turbo`, `gpt-3.5-turbo` | `OPENAI_API_KEY` |
| **Anthropic** | `claude-3-opus`, `claude-3-sonnet` | `ANTHROPIC_API_KEY` |
| **NVIDIA NIM** | `meta/llama3-70b-instruct`, etc. | `NVIDIA_API_KEY` |
| **Ollama** | `llama3`, `mistral`, `phi3` | `OLLAMA_BASE_URL` (default: http://localhost:11434/v1) |

## MCP Servers

| Server Type | Description | Common Use Case |
| --- | --- | --- |
| **Database** | SQL / NoSQL database integrations | Querying application data |
| **Filesystem** | Local or remote file access | Reading/writing configurations and logs |
| **REST API** | Generic HTTP integrations | Interacting with external SaaS platforms |

## Custom Server Guide

Adding a custom MCP server is straightforward. Any MCP-compliant server that implements `@server.list_tools()` and `@server.call_tool()` over an HTTP transport (e.g., using Starlette + Uvicorn) can be plugged directly into the gateway. Just add it to your `workflow.yaml`:

```yaml
mcp_servers:
  - name: my-custom-server
    url: http://custom-server:8000
```

## OpenClaw Integration

Export your configured MCP tools as OpenClaw-compatible skills with a single command. This allows external agents to natively understand and utilize your MCP ecosystem.

```bash
amcpg skills openclaw-setup --output ./skills.json
```

## Observability

We use OpenTelemetry to trace every step of your LLM interactions and tool calls. 
- Ensure `OTEL_EXPORTER_OTLP_ENDPOINT` is set in your environment.
- Start Arize Phoenix locally (default port `6006`) to view your traces: `PHOENIX_PORT=6006 python -m phoenix.server`

## Contributing

We welcome contributions! Please see our [CONTRIBUTING.md](./CONTRIBUTING.md) for details on how to set up the development environment, run tests, and submit pull requests.

## License

This project is licensed under the Apache-2.0 License - see the [LICENSE](./LICENSE) file for details.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=sinh/agentic-mcp-gateway&type=Date)](https://star-history.com/#sinh/agentic-mcp-gateway&Date)
