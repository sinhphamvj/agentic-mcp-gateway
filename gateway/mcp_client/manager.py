# SPDX-License-Identifier: Apache-2.0
"""Manager for multiple MCP server connections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from gateway.mcp_client.http_client import MCPHttpClient
from gateway.mcp_client.stdio_client import MCPStdioClient

TransportName = Literal["http", "stdio"]


class MCPClient(Protocol):
    """Protocol shared by MCP transport clients."""

    async def connect(self) -> object:
        """Connect to an MCP server."""

    async def list_tools(self) -> list[object]:
        """List tools exposed by an MCP server."""

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> str:
        """Call a tool on an MCP server."""

    async def cleanup(self) -> None:
        """Release transport resources."""


@dataclass(slots=True)
class ServerConfig:
    """Configuration for one MCP server connection."""

    name: str
    transport: TransportName | str
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)


class MCPConnectionManager:
    """Register, connect, and dispatch calls across multiple MCP servers."""

    def __init__(self) -> None:
        """Initialize an empty connection registry."""
        self._servers: dict[str, ServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}

    @property
    def connected_servers(self) -> dict[str, MCPClient]:
        """Return currently connected client instances keyed by server name."""
        return dict(self._clients)

    def register(self, name: str, config: ServerConfig) -> None:
        """Register a server configuration.

        Args:
            name: Registry name used for future tool calls.
            config: MCP server connection settings.
        """
        self._servers[name] = config

    async def connect_all(self) -> None:
        """Connect all registered servers."""
        try:
            for name, config in self._servers.items():
                client = self._build_client(config)
                await client.connect()
                self._clients[name] = client
        except Exception:
            await self.cleanup_all()
            raise

    async def list_all_tools(self) -> dict[str, list[object]]:
        """List tools for every connected MCP server."""
        tools_by_server: dict[str, list[object]] = {}
        for name, client in self._clients.items():
            tools_by_server[name] = await client.list_tools()
        return tools_by_server

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> str:
        """Call a tool on a connected server.

        Args:
            server_name: Registered server name.
            tool_name: MCP tool name.
            arguments: Tool input arguments.

        Raises:
            KeyError: If the server is not connected.
        """
        client = self._clients.get(server_name)
        if client is None:
            raise KeyError(f"Server '{server_name}' is not connected.")
        return await client.call_tool(tool_name, arguments)

    async def cleanup_all(self) -> None:
        """Clean up all connected clients."""
        for client in self._clients.values():
            await client.cleanup()
        self._clients.clear()

    def _build_client(self, config: ServerConfig) -> MCPClient:
        """Build the correct transport client for a server config."""
        if config.transport == "http":
            if not config.url:
                raise ValueError(f"HTTP server '{config.name}' requires a URL.")
            return MCPHttpClient(config.url)

        if config.transport == "stdio":
            if not config.command:
                raise ValueError(f"Stdio server '{config.name}' requires a command.")
            return MCPStdioClient(config.command, config.args)

        raise ValueError(f"Unknown transport: {config.transport}")
