# SPDX-License-Identifier: Apache-2.0
"""Tests for the LangGraph gateway orchestrator."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, get_args, get_type_hints

import pytest

from gateway.core.models import (
    IntentConfig,
    LLMConfig,
    LLMProvider,
    MCPServerConfig,
    WorkflowConfig,
)
from gateway.core.orchestrator import GatewayOrchestrator
from gateway.core.state import GatewayState


def test_gateway_state_schema_uses_add_messages_annotation() -> None:
    """GatewayState uses the LangGraph add_messages reducer for messages."""
    from langgraph.graph.message import add_messages

    hints = get_type_hints(GatewayState, include_extras=True)

    assert get_args(hints["messages"]) == (list, add_messages)
    assert hints["intent"] is str
    assert hints["active_server"] is str
    assert hints["response"] is str


@pytest.mark.asyncio
async def test_orchestrator_setup_registers_servers_and_compiles_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """setup registers MCP servers, connects them, and compiles the graph."""
    import gateway.core.orchestrator as orchestrator_module

    fake_manager = FakeMCPManager()
    fake_llm = FakeWorkflowLLM(intent="lookup")
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(make_workflow_config())

    await orchestrator.setup()

    assert fake_manager.registered == [
        ("db", "http", "http://localhost:8000/mcp", None, []),
    ]
    assert fake_manager.connected is True
    assert orchestrator.workflow is not None
    assert orchestrator.checkpointer is not None


@pytest.mark.asyncio
async def test_orchestrator_runs_full_workflow_with_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run executes classification, an agent node, MCP tool call, and response compile."""
    import gateway.core.orchestrator as orchestrator_module

    fake_manager = FakeMCPManager()
    fake_llm = FakeWorkflowLLM(intent="lookup")
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(make_workflow_config())
    await orchestrator.setup()

    response = await orchestrator.run("lookup customer 42", thread_id="thread-1")

    # F2: the response is now synthesised by the second LLM call,
    # not the old raw-string-join of tool_results.
    assert response == "Found Customer Alice with ID 42"
    assert fake_llm.structured_calls[0]["response_model"].__name__ == "IntentClassification"
    assert fake_llm.chat_calls[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup_customer",
                "description": "Lookup a customer",
                "parameters": {
                    "type": "object",
                    "properties": {"customer_id": {"type": "string"}},
                    "required": ["customer_id"],
                },
            },
        }
    ]
    assert fake_manager.tool_calls == [
        ("db", "lookup_customer", {"customer_id": "42"}),
    ]
    # Verify the second LLM call received the tool result
    assert len(fake_llm.chat_calls) >= 2
    second_call_messages = fake_llm.chat_calls[1]["messages"]
    assert any(m.get("role") == "tool" for m in second_call_messages), (  # type: ignore[attr-defined]
        "Second LLM call should include tool-role messages"
    )


@pytest.mark.asyncio
async def test_agent_node_returns_model_text_when_no_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent nodes return assistant text when the model does not request tools."""
    import gateway.core.orchestrator as orchestrator_module

    fake_manager = FakeMCPManager()
    fake_llm = FakeWorkflowLLM(intent="lookup", tool_calls=[])
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(make_workflow_config())
    await orchestrator.setup()
    node = orchestrator._create_agent_node(orchestrator.config.intents[0])

    update = await node(
        {
            "messages": [{"role": "user", "content": "lookup customer 42"}],
            "intent": "lookup",
            "active_server": "db",
            "tool_results": [],
            "response": "",
            "metadata": {},
        }
    )

    # F2: when no tool call, the agent returns the LLM response directly
    assert update["response"] == "Found Customer Alice with ID 42"
    assert update["tool_results"] == []
    assert fake_manager.tool_calls == []


@pytest.mark.asyncio
async def test_unknown_handler_uses_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown intent handling delegates to LangGraph interrupt for human input."""
    import gateway.core.orchestrator as orchestrator_module

    prompts: list[dict[str, object]] = []

    def fake_interrupt(value: dict[str, object]) -> str:
        prompts.append(value)
        return "Manual routing required"

    monkeypatch.setattr(orchestrator_module, "interrupt", fake_interrupt)

    orchestrator = GatewayOrchestrator(make_workflow_config())
    update = await orchestrator._unknown_handler(
        {
            "messages": [{"role": "user", "content": "mystery"}],
            "intent": "UNKNOWN",
            "active_server": "",
            "tool_results": [],
            "response": "",
            "metadata": {"confidence": 0.1},
        }
    )

    assert prompts == [
        {
            "reason": "Unknown intent",
            "message": "mystery",
            "metadata": {"confidence": 0.1},
        }
    ]
    assert update["response"] == "Manual routing required"


@pytest.mark.asyncio
async def test_teardown_cleans_up_mcp_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """teardown delegates cleanup to the MCP connection manager."""
    import gateway.core.orchestrator as orchestrator_module

    fake_manager = FakeMCPManager()
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(
        orchestrator_module,
        "LLMClient",
        lambda config: FakeWorkflowLLM(intent="lookup"),
    )

    orchestrator = GatewayOrchestrator(make_workflow_config())
    await orchestrator.setup()
    await orchestrator.teardown()

    assert fake_manager.cleaned is True


class FakeMCPManager:
    """Fake MCP connection manager used by orchestrator tests."""

    def __init__(self) -> None:
        self.registered: list[tuple[str, str, str | None, str | None, list[str]]] = []
        self.connected = False
        self.cleaned = False
        self.tool_calls: list[tuple[str, str, dict[str, object]]] = []

    def register(self, name: str, config: Any) -> None:
        """Record registered server configs."""
        self.registered.append((name, config.transport, config.url, config.command, config.args))

    async def connect_all(self) -> None:
        """Record connection setup."""
        self.connected = True

    async def list_all_tools(self) -> dict[str, list[object]]:
        """Return one fake tool for the database server."""
        return {
            "db": [
                SimpleNamespace(
                    name="lookup_customer",
                    description="Lookup a customer",
                    inputSchema={
                        "type": "object",
                        "properties": {"customer_id": {"type": "string"}},
                        "required": ["customer_id"],
                    },
                )
            ]
        }

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> str:
        """Record tool calls and return a fake result."""
        self.tool_calls.append((server_name, tool_name, arguments))
        return "Customer Alice"

    async def cleanup_all(self) -> None:
        """Record cleanup."""
        self.cleaned = True


class FakeWorkflowLLM:
    """Fake LLM client for workflow tests."""

    def __init__(self, intent: str, tool_calls: list[object] | None = None) -> None:
        self.intent = intent
        self.tool_calls = (
            [
                SimpleNamespace(
                    function=SimpleNamespace(
                        name="lookup_customer",
                        arguments='{"customer_id": "42"}',
                    )
                )
            ]
            if tool_calls is None
            else tool_calls
        )
        self.structured_calls: list[dict[str, object]] = []
        self.chat_calls: list[dict[str, object]] = []

    async def structured_output(
        self,
        messages: list[dict[str, str]],
        response_model: type,
    ) -> object:
        """Return a configured intent classification."""
        self.structured_calls.append({"messages": messages, "response_model": response_model})
        return response_model(intent=self.intent, confidence=0.93)

    async def chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> object:
        """Return a fake chat response.

        First call (no ``tool``-role message in input) → return ``tool_calls``.
        Subsequent calls (tool feedback present) → return synthesised text.
        """
        self.chat_calls.append({"messages": messages, "tools": tools})

        has_tool_role = any(m.get("role") == "tool" for m in messages)

        if self.tool_calls and not has_tool_role:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_0_lookup_customer",
                                    function=SimpleNamespace(
                                        name="lookup_customer",
                                        arguments='{"customer_id": "42"}',
                                    ),
                                )
                            ],
                        )
                    )
                ]
            )

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Found Customer Alice with ID 42",
                        tool_calls=None,
                    )
                )
            ]
        )


def make_workflow_config() -> WorkflowConfig:
    """Build a minimal workflow config for orchestrator tests."""
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
    )
