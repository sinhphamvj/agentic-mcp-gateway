# SPDX-License-Identifier: Apache-2.0
"""Tests for MCP client transports and connection management."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from gateway.mcp_client.http_client import MCPHttpClient
from gateway.mcp_client.manager import MCPConnectionManager, ServerConfig
from gateway.mcp_client.stdio_client import MCPStdioClient


class FakeTransportContext:
    """Async context manager that mimics MCP transport factories."""

    def __init__(self, *streams: object) -> None:
        self.streams = streams
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> tuple[object, ...]:
        self.entered = True
        return self.streams

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        self.exited = True


class FakeClientSession:
    """Async context manager that mimics mcp.ClientSession."""

    def __init__(self, read_stream: object, write_stream: object) -> None:
        self.read_stream = read_stream
        self.write_stream = write_stream
        self.initialized = False
        self.exited = False
        self.tools = [
            SimpleNamespace(name="add", description="Add two numbers"),
            SimpleNamespace(name="subtract", description="Subtract two numbers"),
        ]

    async def __aenter__(self) -> FakeClientSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        self.exited = True

    async def initialize(self) -> None:
        self.initialized = True

    async def list_tools(self) -> SimpleNamespace:
        return SimpleNamespace(tools=self.tools)

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> SimpleNamespace:
        return SimpleNamespace(content=[SimpleNamespace(text=f"{tool_name}:{arguments}")])


@pytest.mark.asyncio
async def test_http_client_connect_list_call_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP client initializes, lists tools, calls tools, and closes resources."""
    import gateway.mcp_client.http_client as http_module

    transports: list[FakeTransportContext] = []
    sessions: list[FakeClientSession] = []

    def fake_streamablehttp_client(url: str) -> FakeTransportContext:
        assert url == "http://localhost:8000/mcp"
        context = FakeTransportContext("http-read", "http-write", lambda: "session-id")
        transports.append(context)
        return context

    def fake_client_session(read_stream: object, write_stream: object) -> FakeClientSession:
        session = FakeClientSession(read_stream, write_stream)
        sessions.append(session)
        return session

    monkeypatch.setattr(http_module, "streamablehttp_client", fake_streamablehttp_client)
    monkeypatch.setattr(http_module, "ClientSession", fake_client_session)

    client = MCPHttpClient("http://localhost:8000/mcp")
    session = await client.connect()

    assert session is sessions[0]
    assert session.initialized is True
    assert transports[0].entered is True
    assert await client.list_tools() == session.tools
    assert await client.call_tool("add", {"a": 2, "b": 3}) == "add:{'a': 2, 'b': 3}"

    await client.cleanup()

    assert client.session is None
    assert session.exited is True
    assert transports[0].exited is True


@pytest.mark.asyncio
async def test_stdio_client_connect_list_call_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stdio client initializes, lists tools, calls tools, and closes resources."""
    import gateway.mcp_client.stdio_client as stdio_module

    transports: list[FakeTransportContext] = []
    sessions: list[FakeClientSession] = []
    server_params: list[Any] = []

    def fake_stdio_client(params: object) -> FakeTransportContext:
        server_params.append(params)
        context = FakeTransportContext("stdio-read", "stdio-write")
        transports.append(context)
        return context

    def fake_client_session(read_stream: object, write_stream: object) -> FakeClientSession:
        session = FakeClientSession(read_stream, write_stream)
        sessions.append(session)
        return session

    monkeypatch.setattr(stdio_module, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(stdio_module, "ClientSession", fake_client_session)

    client = MCPStdioClient("python", ["server.py"])
    session = await client.connect()

    assert server_params[0].command == "python"
    assert server_params[0].args == ["server.py"]
    assert session is sessions[0]
    assert session.initialized is True
    assert await client.list_tools() == session.tools
    assert await client.call_tool("subtract", {"a": 5, "b": 2}) == "subtract:{'a': 5, 'b': 2}"

    await client.cleanup()

    assert client.session is None
    assert session.exited is True
    assert transports[0].exited is True


@pytest.mark.asyncio
async def test_clients_raise_when_used_before_connect() -> None:
    """Transport clients reject list/call operations before connect."""
    http_client = MCPHttpClient("http://localhost:8000/mcp")
    stdio_client = MCPStdioClient("python", ["server.py"])

    for client in (http_client, stdio_client):
        with pytest.raises(RuntimeError, match="Not connected"):
            await client.list_tools()
        with pytest.raises(RuntimeError, match="Not connected"):
            await client.call_tool("add", {"a": 1, "b": 2})


@pytest.mark.asyncio
async def test_clients_support_async_context_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both clients connect and clean up through async context managers."""
    import gateway.mcp_client.http_client as http_module
    import gateway.mcp_client.stdio_client as stdio_module

    monkeypatch.setattr(
        http_module,
        "streamablehttp_client",
        lambda url: FakeTransportContext("http-read", "http-write", lambda: None),
    )
    monkeypatch.setattr(http_module, "ClientSession", FakeClientSession)
    monkeypatch.setattr(
        stdio_module,
        "stdio_client",
        lambda params: FakeTransportContext("stdio-read", "stdio-write"),
    )
    monkeypatch.setattr(stdio_module, "ClientSession", FakeClientSession)

    async with MCPHttpClient("http://localhost:8000/mcp") as http_client:
        assert http_client.session is not None
        assert http_client.session.initialized is True
    assert http_client.session is None

    async with MCPStdioClient("python", ["server.py"]) as stdio_client:
        assert stdio_client.session is not None
        assert stdio_client.session.initialized is True
    assert stdio_client.session is None


@pytest.mark.asyncio
async def test_connection_manager_registers_connects_lists_calls_and_cleans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection manager coordinates multiple configured MCP servers."""
    import gateway.mcp_client.manager as manager_module

    cleaned: list[str] = []

    class FakeManagedClient:
        def __init__(self, server_id: str, args: list[str] | None = None) -> None:
            self.server_id = server_id
            self.args = args or []
            self.connected = False

        async def connect(self) -> None:
            self.connected = True

        async def list_tools(self) -> list[str]:
            return [f"{self.server_id}:add", f"{self.server_id}:subtract"]

        async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> str:
            return f"{self.server_id}:{tool_name}:{arguments}"

        async def cleanup(self) -> None:
            cleaned.append(self.server_id)

    monkeypatch.setattr(manager_module, "MCPHttpClient", FakeManagedClient)
    monkeypatch.setattr(manager_module, "MCPStdioClient", FakeManagedClient)

    manager = MCPConnectionManager()
    manager.register(
        "remote",
        ServerConfig(name="remote", transport="http", url="http://localhost:8000/mcp"),
    )
    manager.register(
        "local",
        ServerConfig(name="local", transport="stdio", command="python", args=["server.py"]),
    )

    await manager.connect_all()

    assert await manager.list_all_tools() == {
        "remote": ["http://localhost:8000/mcp:add", "http://localhost:8000/mcp:subtract"],
        "local": ["python:add", "python:subtract"],
    }
    assert (
        await manager.call_tool("remote", "add", {"a": 2, "b": 3})
        == "http://localhost:8000/mcp:add:{'a': 2, 'b': 3}"
    )

    await manager.cleanup_all()

    assert sorted(cleaned) == ["http://localhost:8000/mcp", "python"]
    assert manager.connected_servers == {}


@pytest.mark.asyncio
async def test_connection_manager_reports_configuration_errors() -> None:
    """Connection manager raises clear errors for invalid use."""
    manager = MCPConnectionManager()

    with pytest.raises(KeyError, match="not connected"):
        await manager.call_tool("missing", "add", {})

    manager.register("unknown", ServerConfig(name="unknown", transport="websocket"))
    with pytest.raises(ValueError, match="Unknown transport"):
        await manager.connect_all()

    missing_url = MCPConnectionManager()
    missing_url.register("remote", ServerConfig(name="remote", transport="http"))
    with pytest.raises(ValueError, match="requires a URL"):
        await missing_url.connect_all()

    missing_command = MCPConnectionManager()
    missing_command.register("local", ServerConfig(name="local", transport="stdio"))
    with pytest.raises(ValueError, match="requires a command"):
        await missing_command.connect_all()
