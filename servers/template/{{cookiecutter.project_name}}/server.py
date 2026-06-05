# SPDX-License-Identifier: Apache-2.0
"""Low-level MCP server skeleton exposed over Streamable HTTP."""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

TOOL_NAMES = [name.strip() for name in "{{ cookiecutter.tool_names }}".split(",") if name.strip()]
server = Server("{{ cookiecutter.project_name }}", version="0.1.0")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List tools exposed by this server."""
    return [
        Tool(
            name=tool_name,
            description=f"Skeleton handler for {tool_name}.",
            inputSchema={"type": "object", "properties": {}},
        )
        for tool_name in TOOL_NAMES
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch tool calls."""
    if name not in TOOL_NAMES:
        text = f"Unknown tool: {name}"
    else:
        text = f"Called {name} with arguments: {arguments}"
    return [TextContent(type="text", text=text)]


def create_app() -> Starlette:
    """Create the Starlette app exposing the MCP endpoint."""
    session_manager = StreamableHTTPSessionManager(app=server, stateless=True, json_response=True)
    mcp_app = StreamableHTTPASGIApp(session_manager)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    return Starlette(routes=[Route("/mcp", endpoint=mcp_app)], lifespan=lifespan)


def main() -> None:
    """Run the MCP server."""
    port = int(os.environ.get("MCP_PORT", "{{ cookiecutter.port }}"))
    uvicorn.run(create_app(), host="127.0.0.1", port=port)


class StreamableHTTPASGIApp:
    """ASGI wrapper for the MCP Streamable HTTP session manager."""

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self.session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.session_manager.handle_request(scope, receive, send)


if __name__ == "__main__":
    main()
