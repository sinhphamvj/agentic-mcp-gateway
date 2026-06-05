# Reddit Post

**Target Subreddits:** r/Python, r/MachineLearning, r/LocalLLaMA, r/LangChain

**Title:** I built an open-source gateway to connect any LLM to any MCP server using LangGraph

**Body:**

Hey everyone,

If you've been working with AI agents recently, you've probably run into the Model Context Protocol (MCP). It's great for exposing tools, but managing the N-to-N integration nightmare between different LLM providers (OpenAI, Anthropic, local Ollama models) and various MCP servers quickly becomes a headache. You end up writing tons of boilerplate for routing, tracing, and standardizing inputs.

To solve this, I built **agentic-mcp-gateway** — an open-source Python framework that connects any LLM to any number of MCP tool servers through a single LangGraph-powered gateway.

**How it works:**
1. A User Request comes in.
2. An Intent Classifier (built as a LangGraph node) uses Pydantic structured outputs to determine the goal.
3. The request is routed to the specialized Agent.
4. The Agent executes tools on the corresponding MCP Server (DB, REST API, Custom).
5. The response is compiled and returned with full OpenTelemetry tracing.

**Key Features:**
- **Swappable LLMs:** Easily switch between OpenAI, NVIDIA NIM, Anthropic, or Ollama via a simple YAML config. No code changes required.
- **Built-in Intent Routing:** Powered by LangGraph >= 0.2 and Pydantic >= 2.0.
- **Observability Out-of-the-Box:** Every tool call is traced with OpenTelemetry and Arize-Phoenix.
- **Human-in-the-loop:** Built-in support for LangGraph `interrupt()` for destructive operations.
- **Modern Python:** Written in Python 3.12+, managed with `uv`, and fully async (Starlette + Uvicorn).

I'd love for you to check it out, give it a spin, and let me know what you think! Feedback, issues, and PRs are incredibly welcome.

**GitHub Repo:** [Insert Link Here]

Thanks!
