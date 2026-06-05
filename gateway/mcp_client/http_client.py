# SPDX-License-Identifier: Apache-2.0
"""Async MCP HTTP client for connecting to remote MCP servers."""

from __future__ import annotations

from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from gateway.observability.tracer import trace_tool_call


class MCPHttpClient:
    """MCP client for Streamable HTTP servers."""

    def __init__(self, url: str, *, server_name: str | None = None) -> None:
        """Initialize the HTTP client.

        Args:
            url: Streamable HTTP MCP endpoint URL.
            server_name: Logical server name for tracing. Falls back to *url*.
        """
        self.url = url
        self.server_name = server_name or url
        self._exit_stack = AsyncExitStack()
        self.session: ClientSession | None = None

    async def connect(self) -> ClientSession:
        """Establish the HTTP transport and initialize the MCP session."""
        transport = await self._exit_stack.enter_async_context(streamablehttp_client(self.url))
        read_stream, write_stream, _get_session_id = transport
        self.session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self.session.initialize()
        return self.session

    async def list_tools(self) -> list[Any]:
        """List tools exposed by the connected MCP server."""
        if self.session is None:
            raise RuntimeError("Not connected. Call connect() first.")
        result = await self.session.list_tools()
        return list(result.tools)

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> str:
        """Call a tool on the connected MCP server and return its first text result."""
        if self.session is None:
            raise RuntimeError("Not connected. Call connect() first.")
        with trace_tool_call(self.server_name, tool_name, arguments):
            result = await self.session.call_tool(tool_name, arguments)
        if not result.content:
            return ""
        first_content = result.content[0]
        return str(getattr(first_content, "text", first_content))

    async def cleanup(self) -> None:
        """Close the session and transport resources."""
        await self._exit_stack.aclose()
        self.session = None

    async def __aenter__(self) -> MCPHttpClient:
        """Connect when entering an async context manager."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Clean up when leaving an async context manager."""
        await self.cleanup()
