# SPDX-License-Identifier: Apache-2.0
"""End-to-end integration tests for the gateway pipeline.

These tests exercise the **full** pathway:

    workflow.yaml -> load_config -> GatewayOrchestrator.setup
    -> intent classifier (fake LLM) -> agent node
    -> real MCP server (subprocess) tool call
    -> response synthesis -> run() return value

The LLM is replaced with a deterministic fake, but the MCP server is a
real subprocess started with ``subprocess.Popen``.  This is the gap
between unit tests (everything mocked) and server tests (MCP only) and
is where regressions in the glue logic hide.

Marked with ``@pytest.mark.integration`` so they can be excluded from
fast CI runs:

    uv run pytest --ignore-glob='**/integration'
    uv run pytest tests/integration -m integration
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from gateway.core.config import load_config
from gateway.core.orchestrator import GatewayOrchestrator
from gateway.mcp_client.http_client import MCPHttpClient
from servers.database.db_helper import create_sample_db

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Bind a socket to port 0 to discover an unused TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_database_server(db_path: Path, port: int) -> subprocess.Popen[str]:
    """Start the SQLite MCP server on the given port."""
    env = os.environ.copy()
    env["DB_PATH"] = str(db_path)
    env["MCP_PORT"] = str(port)
    return subprocess.Popen(
        [sys.executable, "servers/database/server.py"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _stop_server(process: subprocess.Popen[str]) -> None:
    """Terminate the server subprocess; surface stderr on failure."""
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    if process.returncode not in (0, -15, -9):  # -15 = SIGTERM, -9 = SIGKILL
        _, stderr = process.communicate()
        raise AssertionError(f"Database server exited with code {process.returncode}: {stderr}")


async def _wait_for_server(url: str) -> None:
    """Poll the MCP server until it exposes the expected tools."""
    port = int(url.split(":")[-1].split("/")[0])
    deadline = time.monotonic() + 10
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if not await _port_is_ready("127.0.0.1", port):
            await asyncio.sleep(0.1)
            continue
        client = MCPHttpClient(url)
        try:
            await client.connect()
            tools = await client.list_tools()
        finally:
            await client.cleanup()
        names = {tool.name for tool in tools}
        if {"list_tables", "query_database"}.issubset(names):
            return
        last_error = AssertionError(f"Missing tools, got: {names}")
        await asyncio.sleep(0.1)
    raise AssertionError(f"Timed out waiting for MCP server at {url}: {last_error}")


async def _port_is_ready(host: str, port: int) -> bool:
    """Return whether a TCP port accepts connections."""
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except OSError:
        return False
    writer.close()
    await writer.wait_closed()
    return True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def database_server(tmp_path: Path) -> dict[str, str]:
    """Boot a real database MCP server on a free port and yield its URL."""
    db_path = tmp_path / "sample.db"
    create_sample_db(db_path)

    port = _find_free_port()
    process = _start_database_server(db_path, port)
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        await _wait_for_server(url)
        yield {"url": url, "name": "demo-db"}
    finally:
        _stop_server(process)


@pytest.fixture
def workflow_yaml(tmp_path: Path) -> Path:
    """Write a minimal workflow.yaml for integration tests and return its path."""
    config = """
llm:
  provider: openai
  model_name: gpt-test
  api_key_env: OPENAI_API_KEY
  temperature: 0.0
  max_tokens: 1024

mcp_servers:
  - name: demo-db
    transport: http
    url: ${TEST_MCP_URL}
    description: "Demo SQLite database for integration tests"

intents:
  - name: QUERY
    description: "Ask questions about the database — users, products, orders"
    mcp_server: demo-db
    system_prompt: |
      You are a helpful database assistant. Use the query_database tool.

  - name: SCHEMA
    description: "Ask about database structure or list tables"
    mcp_server: demo-db
    system_prompt: |
      You are a database schema expert. Use the list_tables tool.

gateway_port: 8001
enable_tracing: false
human_in_the_loop_intents: []
max_tool_rounds: 3
"""
    path = tmp_path / "workflow.yaml"
    path.write_text(config, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeFullWorkflowLLM:
    """Deterministic LLM fake that drives the orchestrator end-to-end.

    The fake's first call to ``structured_output`` (intent classifier)
    returns a fixed intent; the first ``chat`` call returns a fixed
    tool call; the second ``chat`` call (with tool feedback present)
    echoes a synthesis string.
    """

    def __init__(self, intent: str, tool_name: str, tool_arguments: str) -> None:
        self.intent = intent
        self.tool_name = tool_name
        self.tool_arguments = tool_arguments
        self.structured_calls: list[dict[str, object]] = []
        self.chat_calls: list[dict[str, object]] = []

    async def structured_output(
        self,
        messages: list[dict[str, str]],
        response_model: type,
    ) -> object:
        """Return the configured intent classification."""
        self.structured_calls.append({"messages": messages, "response_model": response_model})
        return response_model(intent=self.intent, confidence=0.95)

    async def chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> object:
        """Return a tool call on the first turn, synthesised text on the second."""
        self.chat_calls.append({"messages": messages, "tools": tools})

        has_tool_role = any(m.get("role") == "tool" for m in messages)
        if not has_tool_role:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_0",
                                    function=SimpleNamespace(
                                        name=self.tool_name,
                                        arguments=self.tool_arguments,
                                    ),
                                )
                            ],
                        )
                    )
                ]
            )

        synthesis = (
            "The database has 3 tables: orders, products, users."
            if self.tool_name == "list_tables"
            else "First user is Alice with email alice@example.com."
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=synthesis, tool_calls=None))]
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_intent_calls_query_database_on_real_server(
    monkeypatch: pytest.MonkeyPatch,
    database_server: dict[str, str],
    workflow_yaml: Path,
) -> None:
    """QUERY intent routes to the real database MCP server and returns data."""
    import gateway.core.orchestrator as orchestrator_module

    monkeypatch.setenv("TEST_MCP_URL", database_server["url"])
    config = load_config(workflow_yaml)

    fake_llm = FakeFullWorkflowLLM(
        intent="QUERY",
        tool_name="query_database",
        tool_arguments='{"sql": "SELECT name, email FROM users ORDER BY id"}',
    )
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", RealMCPConnectionManager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(config)
    try:
        await orchestrator.setup()
        response = await orchestrator.run("Who is the first user?", thread_id="e2e-query-1")
    finally:
        await orchestrator.teardown()

    # Intent classifier was called
    assert len(fake_llm.structured_calls) == 1
    # LLM was invoked at least twice: tool call + synthesis
    assert len(fake_llm.chat_calls) >= 2
    # The real server's output reached the LLM synthesis
    assert "Alice" in response
    assert "alice@example.com" in response


@pytest.mark.integration
@pytest.mark.asyncio
async def test_schema_intent_calls_list_tables_on_real_server(
    monkeypatch: pytest.MonkeyPatch,
    database_server: dict[str, str],
    workflow_yaml: Path,
) -> None:
    """SCHEMA intent routes to list_tables on the real server."""
    import gateway.core.orchestrator as orchestrator_module

    monkeypatch.setenv("TEST_MCP_URL", database_server["url"])
    config = load_config(workflow_yaml)

    fake_llm = FakeFullWorkflowLLM(
        intent="SCHEMA",
        tool_name="list_tables",
        tool_arguments="{}",
    )
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", RealMCPConnectionManager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(config)
    try:
        await orchestrator.setup()
        response = await orchestrator.run("What tables exist?", thread_id="e2e-schema-1")
    finally:
        await orchestrator.teardown()

    # The synthesised response names all three tables the real server
    # created via create_sample_db.
    assert "orders" in response
    assert "products" in response
    assert "users" in response
    # The LLM was called with the list_tables tool spec
    first_chat_tools = fake_llm.chat_calls[0]["tools"]  # type: ignore[attr-defined]
    tool_names = {t["function"]["name"] for t in first_chat_tools}  # type: ignore[union-attr]
    assert tool_names == {"list_tables", "query_database"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_workflow_yaml_loads_and_executes(
    monkeypatch: pytest.MonkeyPatch,
    database_server: dict[str, str],
    workflow_yaml: Path,
) -> None:
    """End-to-end: YAML -> load_config -> orchestrator -> real server -> response."""
    import gateway.core.orchestrator as orchestrator_module

    monkeypatch.setenv("TEST_MCP_URL", database_server["url"])
    # Loading the YAML must succeed and expose the right intents.
    config = load_config(workflow_yaml)
    assert [i.name for i in config.intents] == ["QUERY", "SCHEMA"]
    assert config.mcp_servers[0].name == "demo-db"

    fake_llm = FakeFullWorkflowLLM(
        intent="QUERY",
        tool_name="query_database",
        tool_arguments='{"sql": "SELECT name FROM users WHERE id=1"}',
    )
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", RealMCPConnectionManager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(config)
    try:
        await orchestrator.setup()
        assert orchestrator.workflow is not None
        assert orchestrator.mcp_manager.connected_servers  # type: ignore[attr-defined]
        assert "demo-db" in orchestrator.mcp_manager.connected_servers  # type: ignore[attr-defined]

        response = await orchestrator.run("Look up user 1", thread_id="e2e-full-1")
    finally:
        await orchestrator.teardown()

    assert orchestrator.mcp_manager.connected_servers == {}  # type: ignore[attr-defined]
    assert "Alice" in response


@pytest.mark.integration
@pytest.mark.asyncio
async def test_teardown_disconnects_real_mcp_server(
    monkeypatch: pytest.MonkeyPatch,
    database_server: dict[str, str],
    workflow_yaml: Path,
) -> None:
    """After teardown the connection manager should hold no live clients."""
    import gateway.core.orchestrator as orchestrator_module

    monkeypatch.setenv("TEST_MCP_URL", database_server["url"])
    config = load_config(workflow_yaml)

    fake_llm = FakeFullWorkflowLLM(intent="QUERY", tool_name="list_tables", tool_arguments="{}")
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", RealMCPConnectionManager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(config)
    await orchestrator.setup()
    assert "demo-db" in orchestrator.mcp_manager.connected_servers  # type: ignore[attr-defined]

    await orchestrator.teardown()

    assert orchestrator.mcp_manager.connected_servers == {}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Real MCP manager passthrough
# ---------------------------------------------------------------------------


class RealMCPConnectionManager:
    """Pass-through that re-exports the real MCPConnectionManager.

    The integration tests want the *real* manager (so subprocess
    connections actually happen) while still using
    ``monkeypatch.setattr`` on the symbol that ``orchestrator`` imports.
    """

    def __new__(cls) -> Any:  # pragma: no cover - trivial passthrough
        from gateway.mcp_client.manager import MCPConnectionManager

        return MCPConnectionManager()
