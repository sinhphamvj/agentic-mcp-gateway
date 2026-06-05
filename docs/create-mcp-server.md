# Creating an MCP Server

This guide explains how to build a custom Model Context Protocol (MCP) server in Python and integrate it with the Agentic MCP Gateway.

## Using the `mcp[cli]` SDK

The easiest way to create a new server is by leveraging the low-level Server components from the official `mcp` Python SDK. 

### 1. Initialize the Server

Create a new Python file (e.g., `my_custom_server.py`) and initialize the server instance.

```python
from mcp.server import Server
from pydantic import BaseModel, Field

# Create the server instance
app = Server("my-custom-server")
```

### 2. Defining Tools

You must implement two primary handlers: one to list available tools, and one to execute them.

**Listing Tools:** Use the `@app.list_tools()` decorator to return a list of tool definitions.

```python
from mcp.types import Tool

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools for this server."""
    return [
        Tool(
            name="calculate_sum",
            description="Calculates the sum of two integers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "integer", "description": "First number"},
                    "b": {"type": "integer", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        )
    ]
```

**Calling Tools:** Use the `@app.call_tool()` decorator to handle the execution logic.

```python
from mcp.types import CallToolRequest, CallToolResult, TextContent

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool execution requests."""
    if name == "calculate_sum":
        a = arguments.get("a")
        b = arguments.get("b")
        
        if not isinstance(a, int) or not isinstance(b, int):
            raise ValueError("Arguments 'a' and 'b' must be integers.")
            
        result = a + b
        return [TextContent(type="text", text=f"The sum is: {result}")]
        
    raise ValueError(f"Unknown tool: {name}")
```

### 3. Running the Server

To make the server executable via stdio (standard input/output), add the following block at the bottom of your file.

```python
import asyncio
from mcp.server.stdio import stdio_server

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

## Testing the Server

Always write integration tests for your MCP servers. Use `pytest` and `pytest-asyncio` along with an MCP client to ensure your tools behave as expected over the transport layer.

```python
import pytest
from mcp.client.stdio import stdio_client
from mcp.client.session import ClientSession

@pytest.mark.asyncio
async def test_calculate_sum():
    # Setup client to talk to your server script
    async with stdio_client(["python", "my_custom_server.py"]) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Test list tools
            tools = await session.list_tools()
            assert any(t.name == "calculate_sum" for t in tools.tools)
            
            # Test tool execution
            result = await session.call_tool("calculate_sum", {"a": 5, "b": 10})
            assert result.content[0].text == "The sum is: 15"
```

## Registering in the Gateway

Once your server is ready, register it in your `workflow.yaml` so the gateway can route requests to it.

```yaml
llm:
  provider: openai
  model: gpt-4o

agents:
  - name: math_agent
    description: "An agent that performs mathematical calculations."
    mcp_servers:
      - name: custom_math_server
        command: "python"
        args: ["/absolute/path/to/my_custom_server.py"]
```
