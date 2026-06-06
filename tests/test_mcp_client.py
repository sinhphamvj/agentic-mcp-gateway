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


# ---------------------------------------------------------------------------
# Connection resilience tests (F10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_with_retry_succeeds_on_first_attempt() -> None:
    """with_retry returns immediately when the first attempt succeeds."""
    from gateway.mcp_client.manager import with_retry

    calls: list[int] = []

    async def succeed() -> str:
        calls.append(1)
        return "ok"

    result = await with_retry(succeed, max_retries=3, backoff_base=0.0)
    assert result == "ok"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_with_retry_succeeds_on_third_attempt() -> None:
    """with_retry keeps trying until the call eventually succeeds."""
    from gateway.mcp_client.manager import with_retry

    attempts: list[int] = []

    async def flaky() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("transient")
        return "ok"

    result = await with_retry(flaky, max_retries=5, backoff_base=0.0)
    assert result == "ok"
    assert len(attempts) == 3


@pytest.mark.asyncio
async def test_with_retry_exhausts_max_retries_and_raises_last_exception() -> None:
    """with_retry re-raises the last exception after exhausting attempts."""
    from gateway.mcp_client.manager import with_retry

    attempts: list[int] = []

    async def always_fails() -> str:
        attempts.append(1)
        raise ConnectionError(f"attempt {len(attempts)}")

    with pytest.raises(ConnectionError, match="attempt 3"):
        await with_retry(always_fails, max_retries=2, backoff_base=0.0)
    assert len(attempts) == 3  # 1 initial + 2 retries


@pytest.mark.asyncio
async def test_with_retry_zero_max_retries_means_no_retry() -> None:
    """with_retry with max_retries=0 raises immediately on failure."""
    from gateway.mcp_client.manager import with_retry

    attempts: list[int] = []

    async def always_fails() -> str:
        attempts.append(1)
        raise ConnectionError("nope")

    with pytest.raises(ConnectionError):
        await with_retry(always_fails, max_retries=0, backoff_base=0.0)
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_with_retry_does_not_retry_non_retryable_exceptions() -> None:
    """with_retry re-raises non-retryable exceptions immediately."""
    from gateway.mcp_client.manager import with_retry

    attempts: list[int] = []

    async def boom() -> str:
        attempts.append(1)
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        await with_retry(boom, max_retries=5, backoff_base=0.0)
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_call_tool_retries_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """call_tool retries when the underlying client raises ConnectionError."""
    import gateway.mcp_client.manager as manager_module

    class FlakyClient:
        def __init__(self, server_id: str, args: list[str] | None = None) -> None:
            self.server_id = server_id
            self.args = args or []
            self.connect_calls = 0
            self.tool_calls = 0

        async def connect(self) -> None:
            self.connect_calls += 1

        async def list_tools(self) -> list[str]:
            return []

        async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> str:
            self.tool_calls += 1
            if self.tool_calls < 3:
                raise ConnectionError("dropped")
            return f"{tool_name}:{arguments}"

        async def cleanup(self) -> None:
            pass

    monkeypatch.setattr(manager_module, "MCPHttpClient", FlakyClient)
    monkeypatch.setattr(manager_module, "MCPStdioClient", FlakyClient)

    manager = MCPConnectionManager()
    manager.register(
        "flaky",
        ServerConfig(
            name="flaky",
            transport="http",
            url="http://localhost:8000/mcp",
            max_retries=5,
            backoff_base=0.0,
        ),
    )
    await manager.connect_all(max_retries=0)

    result = await manager.call_tool("flaky", "add", {"a": 1})
    assert result == "add:{'a': 1}"
    assert manager._clients["flaky"].tool_calls == 3  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_call_tool_returns_structured_error_after_retry_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """call_tool returns a JSON error dict when retries are exhausted."""
    import json

    import gateway.mcp_client.manager as manager_module

    class AlwaysFailsClient:
        def __init__(self, server_id: str, args: list[str] | None = None) -> None:
            self.server_id = server_id
            self.args = args or []

        async def connect(self) -> None:
            pass

        async def list_tools(self) -> list[str]:
            return []

        async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> str:
            raise ConnectionError("server down")

        async def cleanup(self) -> None:
            pass

    monkeypatch.setattr(manager_module, "MCPHttpClient", AlwaysFailsClient)
    monkeypatch.setattr(manager_module, "MCPStdioClient", AlwaysFailsClient)

    manager = MCPConnectionManager()
    manager.register(
        "broken",
        ServerConfig(
            name="broken",
            transport="http",
            url="http://localhost:8000/mcp",
            max_retries=2,
            backoff_base=0.0,
        ),
    )
    await manager.connect_all(max_retries=0)

    result = await manager.call_tool("broken", "add", {"a": 1})
    payload = json.loads(result)
    assert payload["server"] == "broken"
    assert payload["tool"] == "add"
    assert "server down" in payload["error"]
    assert "3 attempts" in payload["error"]  # 1 + 2 retries


@pytest.mark.asyncio
async def test_connect_all_retries_each_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """connect_all retries each server's initial connect on failure."""
    import gateway.mcp_client.manager as manager_module

    class FlakyConnectClient:
        instances: list[FlakyConnectClient] = []

        def __init__(self, server_id: str, args: list[str] | None = None) -> None:
            self.server_id = server_id
            self.args = args or []
            self.connect_calls = 0
            self.instances.append(self)

        async def connect(self) -> None:
            self.connect_calls += 1
            if self.connect_calls < 2:
                raise ConnectionError("first attempt fails")

        async def list_tools(self) -> list[str]:
            return []

        async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> str:
            return ""

        async def cleanup(self) -> None:
            pass

    monkeypatch.setattr(manager_module, "MCPHttpClient", FlakyConnectClient)
    monkeypatch.setattr(manager_module, "MCPStdioClient", FlakyConnectClient)

    manager = MCPConnectionManager()
    manager.register(
        "flaky",
        ServerConfig(
            name="flaky",
            transport="http",
            url="http://localhost:8000/mcp",
            backoff_base=0.0,
        ),
    )

    await manager.connect_all(max_retries=2)

    assert "flaky" in manager.connected_servers
    assert FlakyConnectClient.instances[0].connect_calls == 2


@pytest.mark.asyncio
async def test_connect_all_skips_unreachable_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    """connect_all reports failure but does not raise if any server is unreachable.

    The current implementation aborts the whole batch when one server
    fails; this test pins the behaviour so future refactors keep the
    contract explicit.
    """
    import gateway.mcp_client.manager as manager_module

    class AlwaysFailsClient:
        def __init__(self, server_id: str, args: list[str] | None = None) -> None:
            self.server_id = server_id
            self.args = args or []

        async def connect(self) -> None:
            raise ConnectionError("never up")

        async def list_tools(self) -> list[str]:
            return []

        async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> str:
            return ""

        async def cleanup(self) -> None:
            pass

    monkeypatch.setattr(manager_module, "MCPHttpClient", AlwaysFailsClient)
    monkeypatch.setattr(manager_module, "MCPStdioClient", AlwaysFailsClient)

    manager = MCPConnectionManager()
    manager.register(
        "broken",
        ServerConfig(
            name="broken",
            transport="http",
            url="http://localhost:8000/mcp",
            backoff_base=0.0,
        ),
    )

    with pytest.raises(RuntimeError, match="Failed to connect"):
        await manager.connect_all(max_retries=1)


@pytest.mark.asyncio
async def test_health_check_marks_degraded_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """health_check reports a server as degraded when list_tools() fails."""
    import gateway.mcp_client.manager as manager_module

    class BrokenListClient:
        def __init__(self, server_id: str, args: list[str] | None = None) -> None:
            self.server_id = server_id
            self.args = args or []

        async def connect(self) -> None:
            pass

        async def list_tools(self) -> list[str]:
            raise ConnectionError("dead")

        async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> str:
            return ""

        async def cleanup(self) -> None:
            pass

    monkeypatch.setattr(manager_module, "MCPHttpClient", BrokenListClient)
    monkeypatch.setattr(manager_module, "MCPStdioClient", BrokenListClient)

    manager = MCPConnectionManager()
    manager.register(
        "broken",
        ServerConfig(name="broken", transport="http", url="http://localhost:8000/mcp"),
    )
    await manager.connect_all(max_retries=0)

    status = await manager.health_check("broken")
    assert status["status"] == "degraded"
    assert status["failed_attempts"] >= 1
    assert "last_error" in status


@pytest.mark.asyncio
async def test_get_health_reports_all_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_health returns a status dict for every registered server."""
    import gateway.mcp_client.manager as manager_module

    class GoodClient:
        def __init__(self, server_id: str, args: list[str] | None = None) -> None:
            self.server_id = server_id
            self.args = args or []

        async def connect(self) -> None:
            pass

        async def list_tools(self) -> list[str]:
            return ["tool1"]

        async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> str:
            return ""

        async def cleanup(self) -> None:
            pass

    monkeypatch.setattr(manager_module, "MCPHttpClient", GoodClient)
    monkeypatch.setattr(manager_module, "MCPStdioClient", GoodClient)

    manager = MCPConnectionManager()
    manager.register(
        "ok",
        ServerConfig(name="ok", transport="http", url="http://localhost:8000/mcp"),
    )
    await manager.connect_all(max_retries=0)

    health = manager.get_health()
    assert health["ok"]["status"] == "connected"
    # A server that's registered but not yet connected is still surfaced.
    manager.register(
        "not_yet_connected",
        ServerConfig(name="not_yet_connected", transport="http", url="http://localhost:8001/mcp"),
    )
    health = manager.get_health()
    assert "not_yet_connected" in health
    assert health["not_yet_connected"]["status"] == "disconnected"
