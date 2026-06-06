# Getting Started with Agentic MCP Gateway

Welcome to the Agentic MCP Gateway! This guide will walk you through setting up the framework and running your first multi-MCP agent workflow.

## Prerequisites

Before you begin, ensure you have the following installed:

*   **Python 3.12+**: Required for the latest async features and type hinting.
*   **uv**: The fast Python package installer and resolver.
*   **API Keys**: Depending on your LLM provider, you will need at least one of the following:
    *   `OPENAI_API_KEY`
    *   `ANTHROPIC_API_KEY`
    *   `NVIDIA_API_KEY`
    *   Or a running Ollama instance accessible at `OLLAMA_BASE_URL` (default: `http://localhost:11434/v1`).

## Installation

You can install the gateway directly from the source using `uv`.

1.  Clone the repository:
    ```bash
    git clone https://github.com/your-org/agentic-mcp-gateway.git
    cd agentic-mcp-gateway
    ```

2.  Install the package and dependencies using `uv`:
    ```bash
    uv pip install -e .
    ```

    *Tip: To install development dependencies, use `uv pip install -e ".[dev]"`.*

3.  Set up your environment variables. You can create a `.env` file in the root directory:
    ```bash
    export OPENAI_API_KEY="your-api-key-here"
    ```

## First Workflow

The gateway is configured using a YAML file. Let's create a simple workflow that connects an OpenAI agent to a local SQLite MCP server.

1.  Create a file named `workflow.yaml` in your project root:

    ```yaml
    llm:
      provider: openai
      model_name: gpt-4o-mini
      api_key_env: OPENAI_API_KEY
      temperature: 0.0
      max_tokens: 4096

    mcp_servers:
      - name: sqlite_server
        transport: http
        url: http://localhost:8000/mcp
        description: "Local SQLite MCP server"

    intents:
      - name: QUERY
        description: "Ask questions about the local SQLite database"
        mcp_server: sqlite_server
        system_prompt: |
          You are a database assistant. Use the query_database tool
          to answer user questions.
    ```

2.  Run the gateway:

    You can start the gateway using the CLI command provided by the package:
    ```bash
    amcpg serve --config workflow.yaml
    ```

    The gateway will start, initialize the specified MCP servers, set up the LangGraph orchestrator, and listen on `http://localhost:8001` for incoming requests!

## Next Steps

*   Learn about the internal [Architecture](./architecture.md).
*   Create your own custom tools by following the [Create an MCP Server](./create-mcp-server.md) guide.
