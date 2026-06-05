# SPDX-License-Identifier: Apache-2.0
"""Async MCP stdio client for connecting to local MCP servers."""

from __future__ import annotations

from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPStdioClient:
    """MCP client for local stdio MCP servers."""

    def __init__(self, command: str, args: list[str]) -> None:
        """Initialize the stdio client.

        Args:
            command: Executable command used to start the MCP server.
            args: Command arguments.
        """
        self.command = command
        self.args = args
        self._exit_stack = AsyncExitStack()
        self.session: ClientSession | None = None

    async def connect(self) -> ClientSession:
        """Start the stdio transport and initialize the MCP session."""
        server_params = StdioServerParameters(command=self.command, args=self.args)
        read_stream, write_stream = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
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
        result = await self.session.call_tool(tool_name, arguments)
        if not result.content:
            return ""
        first_content = result.content[0]
        return str(getattr(first_content, "text", first_content))

    async def cleanup(self) -> None:
        """Close the session, subprocess, and transport resources."""
        await self._exit_stack.aclose()
        self.session = None

    async def __aenter__(self) -> MCPStdioClient:
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
