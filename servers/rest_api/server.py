# SPDX-License-Identifier: Apache-2.0
"""Low-level MCP REST API bridge exposed over Streamable HTTP."""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

server = Server("agentic-mcp-gateway-rest-api", version="0.1.0")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List REST bridge tools."""
    return [
        Tool(
            name="call_api",
            description="Call an HTTP API with GET or POST and return response text.",
            inputSchema={
                "type": "object",
                "properties": {
                    "method": {"type": "string"},
                    "url": {"type": "string"},
                    "headers": {"type": "object"},
                    "body": {},
                },
                "required": ["method", "url"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch REST bridge tool calls."""
    if name != "call_api":
        result = f"Unknown tool: {name}"
    else:
        result = await call_api(
            method=str(arguments.get("method", "")),
            url=str(arguments.get("url", "")),
            headers=arguments.get("headers"),
            body=arguments.get("body"),
        )
    return [TextContent(type="text", text=result)]


async def call_api(
    method: str,
    url: str,
    headers: object | None = None,
    body: object | None = None,
) -> str:
    """Call an HTTP API and return response text."""
    normalized_method = method.upper()
    if normalized_method not in {"GET", "POST"}:
        return "Only GET and POST methods are allowed."

    request_headers = headers if isinstance(headers, dict) else {}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if normalized_method == "GET":
                response = await client.get(url, headers=request_headers)
            else:
                response = await client.post(
                    url,
                    headers=request_headers,
                    json=body if isinstance(body, dict | list) else None,
                    content=None if isinstance(body, dict | list | None) else str(body),
                )
        return response.text
    except httpx.HTTPError as exc:
        return f"HTTP error: {exc}"


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
    """Run the REST API MCP server."""
    port = int(os.environ.get("MCP_PORT", "8002"))
    uvicorn.run(create_app(), host="127.0.0.1", port=port)


class StreamableHTTPASGIApp:
    """ASGI wrapper for the MCP Streamable HTTP session manager."""

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self.session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.session_manager.handle_request(scope, receive, send)


if __name__ == "__main__":
    main()
