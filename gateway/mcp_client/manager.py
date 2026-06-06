# SPDX-License-Identifier: Apache-2.0
"""Manager for multiple MCP server connections."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import httpx

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
    timeout: int = 30
    max_retries: int = 2
    backoff_base: float = 1.0


RetryableExceptions = (ConnectionError, TimeoutError, httpx.RequestError)


async def with_retry(
    fn: Any,
    *,
    max_retries: int,
    backoff_base: float,
    retryable_exceptions: tuple[type[BaseException], ...] = RetryableExceptions,
) -> Any:
    """Invoke an async callable with exponential-backoff retry.

    Args:
        fn: Zero-argument async callable to invoke on each attempt.
        max_retries: Maximum number of retries after the first attempt.
            Total attempts = ``max_retries + 1``.
        backoff_base: Base sleep in seconds; the wait between attempt
            ``n`` and ``n+1`` is ``backoff_base * (2 ** n)``.
        retryable_exceptions: Exception types that trigger a retry. Any
            other exception is re-raised immediately.

    Returns:
        The value returned by the first successful ``fn()`` call.

    Raises:
        The final exception if every attempt raises a retryable one.
    """
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt < max_retries:
                await asyncio.sleep(backoff_base * (2**attempt))
    assert last_exc is not None  # reachable only when max_retries >= 0 and all attempts failed
    raise last_exc


class MCPConnectionManager:
    """Register, connect, and dispatch calls across multiple MCP servers."""

    def __init__(self) -> None:
        """Initialize an empty connection registry."""
        self._servers: dict[str, ServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}
        self._server_configs: list[ServerConfig] = []
        self._failed_attempts: dict[str, int] = {}
        self._last_error: dict[str, str] = {}
        self._last_success: dict[str, str] = {}

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
        self._server_configs.append(config)

    async def connect_all(self, *, max_retries: int = 1) -> None:
        """Connect all registered servers, retrying each one on failure.

        Args:
            max_retries: Number of retries per server during connect.
                A single retry means one additional attempt beyond the first.

        Raises:
            Exception: The last connection error if any server cannot be
                reached.  All successfully connected clients are torn down
                before the exception propagates.
        """
        failures: list[tuple[str, BaseException]] = []
        for name, config in self._servers.items():
            client = self._build_client(config)
            try:
                await with_retry(
                    client.connect,
                    max_retries=max_retries,
                    backoff_base=config.backoff_base,
                )
            except RetryableExceptions as exc:
                failures.append((name, exc))
                self._record_failure(name, str(exc))
                continue
            except Exception as exc:
                failures.append((name, exc))
                self._record_failure(name, str(exc))
                continue
            self._clients[name] = client
            self._record_success(name)
        if failures:
            await self.cleanup_all()
            last_name, last_exc = failures[-1]
            raise RuntimeError(
                f"Failed to connect to MCP server(s): {last_name}: {last_exc}"
            ) from last_exc

    async def list_all_tools(self) -> dict[str, list[object]]:
        """List tools for every connected MCP server.

        A failing ``list_tools()`` call is reported as an empty tool list
        and the failure is recorded for the per-server health endpoint;
        other servers are still queried.
        """
        tools_by_server: dict[str, list[object]] = {}
        for name, client in self._clients.items():
            try:
                tools_by_server[name] = await client.list_tools()
                self._record_success(name)
            except Exception as exc:
                self._record_failure(name, str(exc))
                tools_by_server[name] = []
        return tools_by_server

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> str:
        """Call a tool on a connected server with exponential-backoff retry.

        Args:
            server_name: Registered server name.
            tool_name: MCP tool name.
            arguments: Tool input arguments.

        Returns:
            Tool result text, or a JSON-encoded structured error dict
            (e.g. ``{"error": "...", "server": "...", "tool": "..."}``)
            when retries are exhausted so the LLM can see the failure
            without the orchestrator crashing.

        Raises:
            KeyError: If the server is not connected.
        """
        client = self._clients.get(server_name)
        if client is None:
            raise KeyError(f"Server '{server_name}' is not connected.")
        config = self._servers.get(server_name)
        max_retries = config.max_retries if config is not None else 0
        backoff_base = config.backoff_base if config is not None else 1.0
        try:
            result = await with_retry(
                lambda: client.call_tool(tool_name, arguments),
                max_retries=max_retries,
                backoff_base=backoff_base,
            )
        except RetryableExceptions as exc:
            self._record_failure(server_name, str(exc))
            import json

            return json.dumps(
                {
                    "error": f"MCP call failed after {max_retries + 1} attempts: {exc}",
                    "server": server_name,
                    "tool": tool_name,
                }
            )
        except Exception as exc:
            self._record_failure(server_name, str(exc))
            raise
        self._record_success(server_name)
        return str(result)

    async def health_check(self, server_name: str) -> dict[str, object]:
        """Probe a single server with ``list_tools()`` and update its status.

        Args:
            server_name: Registered server name.

        Returns:
            ``{"status": "connected" | "degraded", "last_check": ...}``

        Raises:
            KeyError: If the server is not connected.
        """
        client = self._clients.get(server_name)
        if client is None:
            raise KeyError(f"Server '{server_name}' is not connected.")
        try:
            await client.list_tools()
        except Exception as exc:
            self._record_failure(server_name, str(exc))
            return self._server_status(server_name, status="degraded")
        self._record_success(server_name)
        return self._server_status(server_name, status="connected")

    def get_health(self) -> dict[str, dict[str, object]]:
        """Return per-server health snapshots without touching the wire."""
        result: dict[str, dict[str, object]] = {}
        for name in self._servers:
            status = "connected" if name in self._clients else "disconnected"
            result[name] = self._server_status(name, status=status)
        return result

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

    def _record_success(self, server_name: str) -> None:
        self._failed_attempts[server_name] = 0
        self._last_error.pop(server_name, None)
        self._last_success[server_name] = _utcnow_iso()

    def _record_failure(self, server_name: str, error: str) -> None:
        self._failed_attempts[server_name] = self._failed_attempts.get(server_name, 0) + 1
        self._last_error[server_name] = error

    def _server_status(
        self,
        server_name: str,
        *,
        status: str,
    ) -> dict[str, object]:
        info: dict[str, object] = {
            "status": status,
            "failed_attempts": self._failed_attempts.get(server_name, 0),
        }
        if server_name in self._last_success:
            info["last_success"] = self._last_success[server_name]
        if server_name in self._last_error:
            info["last_error"] = self._last_error[server_name]
        return info


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=UTC).isoformat()
