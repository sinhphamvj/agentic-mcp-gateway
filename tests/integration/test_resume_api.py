# SPDX-License-Identifier: Apache-2.0
"""End-to-end integration test for the HITL pause/resume cycle over HTTP.

This test exercises the full path that the F5 resume endpoint claims to
support — a *real* LangGraph interrupt (not a monkeypatched one):

  1. Client posts a chat-completion request that the LLM fake drives
     into a tool call.
  2. Because the intent is in ``human_in_the_loop_intents``, the agent
     node calls ``langgraph.types.interrupt()`` and the graph pauses.
  3. Client posts to ``/v1/threads/{id}/resume`` with
     ``{"approved": true}``.
  4. The graph resumes, the tool is executed, the LLM synthesises the
     answer, and the response is returned over HTTP.

The MCP server, the LLM client, and the LangGraph runtime are all real
(this is what makes it an integration test).  Only the LLM itself is a
deterministic fake.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from starlette.testclient import TestClient

from gateway.core.orchestrator import GatewayOrchestrator
from gateway.mcp_client.http_client import MCPHttpClient
from servers.database.db_helper import create_sample_db

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Subprocess helpers (mirrored from tests/integration/test_full_workflow.py
# to keep the file self-contained; both files spawn DB servers).
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Bind a socket to port 0 to discover an unused TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_database_server(db_path: Path, port: int) -> subprocess.Popen[str]:
    """Start the SQLite MCP server on the given port."""
    env = {
        "PATH": __import__("os").environ.get("PATH", ""),
        "DB_PATH": str(db_path),
        "MCP_PORT": str(port),
    }
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
    if process.returncode not in (0, -15, -9):
        _, stderr = process.communicate()
        raise AssertionError(f"Database server exited with code {process.returncode}: {stderr}")


async def _wait_for_server(url: str) -> None:
    """Poll the MCP server until it exposes the expected tools."""
    import asyncio
    import time

    port = int(url.split(":")[-1].split("/")[0])
    deadline = time.monotonic() + 10
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
        except OSError:
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def hitl_server() -> dict[str, str]:
    """Boot a real database server and yield its URL.

    Returns a dict so the test can pick up the URL plus the port.
    """
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "sample.db"
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
def hitl_workflow_yaml(tmp_path: Path) -> Path:
    """Write a workflow.yaml that flags the DESTRUCTIVE intent as HITL."""
    config = (
        textwrap.dedent(
            """
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
            description: "Demo SQLite database"

        intents:
          - name: DESTRUCTIVE
            description: "Run a write query (gated by human approval)."
            mcp_server: demo-db
            system_prompt: |
              You are a database assistant that must obtain human
              approval before any non-SELECT query.

        gateway_port: 8001
        enable_tracing: false
        human_in_the_loop_intents:
          - DESTRUCTIVE
        max_tool_rounds: 3
        """
        ).strip()
        + "\n"
    )
    path = tmp_path / "workflow.yaml"
    path.write_text(config, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Fake LLM that drives the full interrupt -> resume cycle
# ---------------------------------------------------------------------------


class FakeDestructiveLLM:
    """LLM fake that always tries to call ``query_database`` for a DELETE.

    First ``chat`` call: returns the tool call.  After the human
    approves via the HTTP resume endpoint, the second ``chat`` call
    synthesises a confirmation string.
    """

    def __init__(self) -> None:
        self.structured_calls: list[dict[str, object]] = []
        self.chat_calls: list[dict[str, object]] = []

    async def structured_output(
        self,
        messages: list[dict[str, str]],
        response_model: type,
    ) -> object:
        self.structured_calls.append({"messages": messages, "response_model": response_model})
        return response_model(intent="DESTRUCTIVE", confidence=0.99)

    async def chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> object:
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
                                        name="query_database",
                                        arguments='{"sql": "DELETE FROM users WHERE id=1"}',
                                    ),
                                )
                            ],
                        )
                    )
                ]
            )

        # After tool result, synthesise confirmation
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Approved and executed: 1 row deleted.",
                        tool_calls=None,
                    )
                )
            ]
        )


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_hitl_pause_resume_cycle_via_http(
    monkeypatch: pytest.MonkeyPatch,
    hitl_server: dict[str, str],
    hitl_workflow_yaml: Path,
) -> None:
    """Full cycle: chat completions -> interrupt -> HTTP resume -> tool executed."""
    import asyncio

    import gateway.core.orchestrator as orchestrator_module

    monkeypatch.setenv("TEST_MCP_URL", hitl_server["url"])

    # Use the real orchestrator + real langgraph interrupt mechanism.
    config_dict = yaml.safe_load(hitl_workflow_yaml.read_text(encoding="utf-8"))
    # Substitute env var manually for this test path.
    raw_url = hitl_server["url"]
    config_dict["mcp_servers"][0]["url"] = raw_url
    from gateway.core.models import WorkflowConfig

    config = WorkflowConfig.model_validate(config_dict)

    fake_llm = FakeDestructiveLLM()
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)
    # Real MCPConnectionManager — we want the real subprocess to be called.

    async def run_cycle() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        orchestrator = GatewayOrchestrator(config)
        # Build the app manually so we can reuse the orchestrator instance.
        app = _build_test_app(str(hitl_workflow_yaml), orchestrator)
        try:
            await orchestrator.setup()
            with TestClient(app) as client:
                first_resp = client.post(
                    "/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": "Delete user 1"}],
                        "thread_id": "hitl-tx-1",
                    },
                )
                resume_resp = client.post(
                    "/v1/threads/hitl-tx-1/resume",
                    json={"approved": True},
                )
                post_resp = client.post(
                    "/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": "anything else"}],
                        "thread_id": "hitl-tx-1",
                    },
                )
            return first_resp.json(), resume_resp.json(), post_resp.json()
        finally:
            await orchestrator.teardown()

    first, resume, post = asyncio.run(run_cycle())

    # The first chat completions call should not contain the final
    # answer — the workflow paused at interrupt() before executing the
    # destructive tool.
    assert first["object"] == "chat.completion"
    first_text = first["choices"][0]["message"]["content"]
    # The first call's response should not be the post-execution synthesis.
    assert "Approved and executed" not in first_text

    # The resume response should reflect the executed tool.
    assert resume["object"] == "thread.resume"
    assert resume["thread_id"] == "hitl-tx-1"
    assert "Approved and executed" in resume["response"]
    assert "1 row deleted" in resume["response"]

    # The LLM should have been called twice: tool call + synthesis.
    assert len(fake_llm.chat_calls) >= 2

    # After resume, the thread should be usable for normal chat.
    assert post["object"] == "chat.completion"


def _build_test_app(workflow_path: str, orchestrator: GatewayOrchestrator) -> Any:
    """Construct a Starlette app bound to the given orchestrator instance.

    We can't use ``create_app(workflow_path)`` directly because that
    constructs its own ``GatewayOrchestrator`` internally.  Instead we
    import the route handlers and replicate the lifespan with our own
    orchestrator.
    """
    from starlette.applications import Starlette
    from starlette.routing import Route

    from gateway.server.app import chat_completions, health, resume_thread

    app = Starlette(
        debug=False,
        routes=[
            Route("/health", endpoint=health, methods=["GET"]),
            Route("/v1/chat/completions", endpoint=chat_completions, methods=["POST"]),
            Route(
                "/v1/threads/{thread_id}/resume",
                endpoint=resume_thread,
                methods=["POST"],
            ),
        ],
        lifespan=_make_lifespan(orchestrator),
    )
    app.state.orchestrator = orchestrator  # type: ignore[attr-defined]
    return app


def _make_lifespan(orchestrator: GatewayOrchestrator) -> Any:  # type: ignore[no-untyped-def]
    """Build a lifespan async-context-manager for the given orchestrator."""

    @asynccontextmanager
    async def lifespan(_app: Any) -> AsyncIterator[None]:
        await orchestrator.setup()
        try:
            yield
        finally:
            await orchestrator.teardown()

    return lifespan
