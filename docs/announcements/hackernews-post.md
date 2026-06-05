# HackerNews Post

**Title:** Show HN: Agentic MCP Gateway – Connect any LLM to any MCP server via LangGraph

**Body:**

Hi HN,

I'm sharing a project I've been working on called agentic-mcp-gateway. It's an open-source Python framework designed to simplify building multi-MCP (Model Context Protocol) agent workflows. 

As MCP gains traction for standardizing tool access, I found myself repeatedly writing boilerplate to connect different LLMs (OpenAI, Anthropic, Ollama) to various MCP servers, while also trying to wire up proper intent routing and observability. 

This project aims to solve that N-to-N integration problem by providing a unified gateway. 

Under the hood, it uses:
- LangGraph for orchestrating the workflow and human-in-the-loop interrupts.
- Pydantic structured outputs for an Intent Classifier node that routes requests to the correct agent.
- Async Starlette + Uvicorn for the HTTP transport.
- OpenTelemetry + Arize-Phoenix for tracing every tool call and agent step.

The entire LLM provider and MCP server topology is configured via a single YAML file, meaning you can swap models or add servers without changing code. 

It requires Python 3.12+ and uses `uv` for dependency management. 

I'd love to hear your thoughts on the architecture, particularly on how the intent routing and OTel integration is handled. 

Repo: [Insert Link Here]

Thanks for taking a look!
