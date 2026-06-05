# DEV.to Article

**Title:** Simplify Your AI Agents: Connecting Any LLM to Any MCP Server with a Unified Gateway
**Tags:** python, ai, opensource, architecture

Building AI agents that interact with external tools has become much easier thanks to the **Model Context Protocol (MCP)**. However, as your architecture grows, you quickly run into a new problem: the N-to-N integration nightmare.

Connecting different LLMs (OpenAI, Anthropic, local Ollama models) to various specialized MCP servers (Databases, REST APIs, custom tools) requires writing extensive boilerplate for intent routing, tool execution, and observability.

Today, I'm excited to introduce **agentic-mcp-gateway**, an open-source Python framework that solves this problem using LangGraph.

### What is agentic-mcp-gateway?

`agentic-mcp-gateway` is a framework that routes user requests through a single LangGraph-powered gateway. It classifies the user's intent, selects the appropriate agent, and executes the necessary tools on the corresponding MCP server.

**Key features include:**
- 🧠 **Swappable LLMs:** Switch between providers without code changes.
- 🔀 **Smart Routing:** Pydantic-powered intent classification via LangGraph.
- 📊 **Observability:** Built-in OpenTelemetry tracing and Arize-Phoenix support.
- ⏸️ **Human-in-the-loop:** Built-in interrupts for safe tool execution.

### Zero-Code Configuration

One of the best features of the gateway is that your LLM providers and MCP topology are entirely configured via YAML. Here is an example of how simple it is to set up a workflow:

```yaml
# workflow.yaml
llm:
  provider: openai
  model: gpt-4o
  # Can easily be swapped to:
  # provider: ollama
  # model: llama3

mcp_servers:
  - name: db-tools
    transport: http
    endpoint: http://localhost:8001/mcp
  - name: github-tools
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]

routing:
  intent_classifier:
    type: pydantic
    strict: true
```

### The Architecture Under the Hood

When a request enters the gateway, it hits an **Intent Classifier** (a LangGraph node) which outputs a strictly typed Pydantic model. Based on this intent, LangGraph routes the execution to specialized agents, which then interface with the configured MCP servers. Finally, a response is compiled and sent back to the user—fully traced via OpenTelemetry.

### Get Started

We've built `agentic-mcp-gateway` on modern Python 3.12+, utilizing `uv`, Starlette, and Pydantic v2.

We would love for you to try it out! Check out the repository, read the setup instructions, and start building scalable agent workflows today.

🔗 **[View agentic-mcp-gateway on GitHub](#)**

If you find it useful, consider leaving a star and contributing!
