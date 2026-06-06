# SPDX-License-Identifier: Apache-2.0
"""Tests for persistent checkpointer behaviour (F6).

The default in-memory checkpointer is exercised in the main
``test_orchestrator.py`` suite.  This file focuses on:

- Config-level validation of ``CheckpointerConfig``.
- Selection of the right backend based on configuration.
- Multi-turn behaviour: two ``run()`` calls with the same
  ``thread_id`` accumulate state; different ``thread_id``s do not.
- That teardown closes the SQLite context manager cleanly.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from gateway.core.models import (
    CheckpointerConfig,
    IntentConfig,
    LLMConfig,
    LLMProvider,
    MCPServerConfig,
    WorkflowConfig,
)
from gateway.core.orchestrator import GatewayOrchestrator


# This test file requires the sqlite backend to be available.
def _sqlite_available() -> bool:
    """Return True if the SqliteSaver package can be imported."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: F401
    except ImportError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _sqlite_available(),
    reason="langgraph-checkpoint-sqlite not installed",
)


def _make_workflow_config(
    checkpointer: CheckpointerConfig | None = None,
) -> WorkflowConfig:
    """Build a minimal workflow config for checkpointer tests."""
    return WorkflowConfig(
        llm=LLMConfig(provider=LLMProvider.OPENAI, model_name="gpt-test"),
        mcp_servers=[MCPServerConfig(name="db", transport="http", url="http://localhost:8000/mcp")],
        intents=[
            IntentConfig(
                name="lookup",
                description="Lookup customer records",
                mcp_server="db",
                system_prompt="Use customer lookup tools.",
            )
        ],
        checkpointer=checkpointer or CheckpointerConfig(),
    )


def test_checkpointer_config_defaults_to_in_memory() -> None:
    """A workflow with no checkpointer config uses in-memory storage."""
    cfg = _make_workflow_config()
    assert cfg.checkpointer.backend == "in_memory"
    assert cfg.checkpointer.path is None


def test_checkpointer_config_accepts_sqlite() -> None:
    """SQLite backend with an explicit path should validate."""
    cfg = CheckpointerConfig(backend="sqlite", path="/tmp/state.db")
    assert cfg.backend == "sqlite"
    assert cfg.path == "/tmp/state.db"


def test_checkpointer_config_rejects_unknown_backend() -> None:
    """Unknown backend values must fail validation."""
    with pytest.raises(ValidationError):
        CheckpointerConfig(backend="redis")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_setup_uses_in_memory_saver_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a checkpointer config, the orchestrator wires up InMemorySaver."""
    from langgraph.checkpoint.memory import InMemorySaver

    import gateway.core.orchestrator as orchestrator_module

    fake_manager = FakeMCPManager()
    fake_llm = EchoWorkflowLLM()
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(_make_workflow_config())
    await orchestrator.setup()

    assert isinstance(orchestrator.checkpointer, InMemorySaver)
    await orchestrator.teardown()


@pytest.mark.asyncio
async def test_setup_uses_sqlite_saver_when_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With backend=sqlite, the orchestrator should hold a SqliteSaver instance."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    import gateway.core.orchestrator as orchestrator_module

    fake_manager = FakeMCPManager()
    fake_llm = EchoWorkflowLLM()
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    cfg = _make_workflow_config(
        checkpointer=CheckpointerConfig(backend="sqlite", path=str(tmp_path / "state.db"))
    )
    orchestrator = GatewayOrchestrator(cfg)
    await orchestrator.setup()

    assert isinstance(orchestrator.checkpointer, SqliteSaver)
    assert (tmp_path / "state.db").exists()
    await orchestrator.teardown()


@pytest.mark.asyncio
async def test_sqlite_checkpointer_uses_default_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When sqlite path is omitted the orchestrator should pick a default."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    import gateway.core.orchestrator as orchestrator_module

    fake_manager = FakeMCPManager()
    fake_llm = EchoWorkflowLLM()
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    monkeypatch.chdir(tmp_path)
    cfg = _make_workflow_config(checkpointer=CheckpointerConfig(backend="sqlite"))
    orchestrator = GatewayOrchestrator(cfg)
    await orchestrator.setup()
    assert isinstance(orchestrator.checkpointer, SqliteSaver)
    await orchestrator.teardown()
    # Default file should be created in the cwd.
    assert (tmp_path / "gateway_state.db").exists()


@pytest.mark.asyncio
async def test_teardown_closes_sqlite_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """After teardown the orchestrator should release the SQLite context manager."""
    import gateway.core.orchestrator as orchestrator_module

    fake_manager = FakeMCPManager()
    fake_llm = EchoWorkflowLLM()
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    cfg = _make_workflow_config(
        checkpointer=CheckpointerConfig(backend="sqlite", path=str(tmp_path / "state.db"))
    )
    orchestrator = GatewayOrchestrator(cfg)
    await orchestrator.setup()
    await orchestrator.teardown()

    assert orchestrator._sqlite_cm is None
    assert orchestrator.checkpointer is None


@pytest.mark.asyncio
async def test_multi_turn_in_memory_accumulates_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two run() calls with the same thread_id should let the LLM see prior turns."""
    import gateway.core.orchestrator as orchestrator_module

    fake_manager = FakeMCPManager()
    fake_llm = EchoWorkflowLLM()
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(_make_workflow_config())
    await orchestrator.setup()

    # First turn.
    first = await orchestrator.run("hello", thread_id="t1")
    # Second turn should include the prior "hello" in the message history
    # the LLM receives.  The fake echoes back the most recent user message.
    second = await orchestrator.run("world", thread_id="t1")

    assert first == "Echo: hello"
    assert second == "Echo: world"

    # The second LLM call should have seen the first user message in its
    # history — that's the persistence checkpointer enables.
    second_call_messages = fake_llm.chat_calls[1]["messages"]  # type: ignore[attr-defined]
    history = [m["content"] for m in second_call_messages if m.get("role") == "user"]
    assert history == ["hello", "world"]

    await orchestrator.teardown()


@pytest.mark.asyncio
async def test_different_thread_ids_have_separate_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two threads should NOT see each other's history."""
    import gateway.core.orchestrator as orchestrator_module

    fake_manager = FakeMCPManager()
    fake_llm = EchoWorkflowLLM()
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(_make_workflow_config())
    await orchestrator.setup()

    await orchestrator.run("for-thread-A", thread_id="A")
    await orchestrator.run("for-thread-B", thread_id="B")

    # The most recent chat call (for thread B) should not contain thread A's
    # message.  The most recent structured_output call (the intent classifier
    # for thread B) should also have only B's user message.
    last_chat_messages = fake_llm.chat_calls[-1]["messages"]  # type: ignore[attr-defined]
    history = [m["content"] for m in last_chat_messages if m.get("role") == "user"]
    assert "for-thread-A" not in history
    assert history == ["for-thread-B"]

    await orchestrator.teardown()


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeMCPManager:
    """Minimal MCP connection manager for checkpointer tests."""

    def __init__(self) -> None:
        self.registered: list[tuple[str, str, str | None, str | None, list[str]]] = []
        self.connected = False
        self.cleaned = False

    def register(self, name: str, config: Any) -> None:
        self.registered.append((name, config.transport, config.url, config.command, config.args))

    async def connect_all(self) -> None:
        self.connected = True

    async def list_all_tools(self) -> dict[str, list[object]]:
        return {"db": []}

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, object]
    ) -> str:
        return ""

    async def cleanup_all(self) -> None:
        self.cleaned = True


class EchoWorkflowLLM:
    """Fake LLM that echoes back the most recent user message."""

    def __init__(self) -> None:
        self.structured_calls: list[dict[str, object]] = []
        self.chat_calls: list[dict[str, object]] = []

    async def structured_output(
        self,
        messages: list[dict[str, str]],
        response_model: type,
    ) -> object:
        self.structured_calls.append({"messages": messages, "response_model": response_model})
        return response_model(intent="lookup", confidence=0.95)

    async def chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> object:
        self.chat_calls.append({"messages": messages, "tools": tools})
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=f"Echo: {last_user}", tool_calls=None)
                )
            ]
        )
