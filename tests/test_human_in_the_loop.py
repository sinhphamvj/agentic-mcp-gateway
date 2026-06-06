# SPDX-License-Identifier: Apache-2.0
"""Tests for human-in-the-loop interrupt behaviour (F4).

When ``WorkflowConfig.human_in_the_loop_intents`` names an intent,
the agent node must call ``interrupt()`` *before* executing any tool
and must honour the approval / rejection returned on resume.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from gateway.core.models import (
    IntentConfig,
    LLMConfig,
    LLMProvider,
    MCPServerConfig,
    WorkflowConfig,
)
from gateway.core.orchestrator import GatewayOrchestrator


@pytest.mark.asyncio
async def test_hitl_interrupts_before_tool_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent should call interrupt() with the proposed tool before executing it."""
    import gateway.core.orchestrator as orchestrator_module

    interrupt_calls: list[dict[str, object]] = []

    def fake_interrupt(value: dict[str, object]) -> dict[str, object]:
        interrupt_calls.append(value)
        return {"approved": True}

    monkeypatch.setattr(orchestrator_module, "interrupt", fake_interrupt)

    fake_manager = FakeMCPManager()
    fake_llm = FakeWorkflowLLM()
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(_make_hitl_config())
    await orchestrator.setup()
    await orchestrator.run("refund order 42", thread_id="t1")

    assert len(interrupt_calls) == 1
    payload = interrupt_calls[0]
    assert payload["type"] == "human_in_the_loop"
    assert payload["intent"] == "refund"
    assert payload["proposed_tool_calls"] == [
        {"name": "process_refund", "arguments": {"order_id": "42"}}
    ]
    assert payload["user_message"] == "refund order 42"

    # Tool should have been executed because we approved
    assert fake_manager.tool_calls == [("db", "process_refund", {"order_id": "42"})]


@pytest.mark.asyncio
async def test_hitl_rejection_skips_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """When interrupt returns approved=False the tool should NOT be executed."""
    import gateway.core.orchestrator as orchestrator_module

    def fake_interrupt(value: dict[str, object]) -> dict[str, object]:
        return {"approved": False, "response": "Refund denied by user."}

    monkeypatch.setattr(orchestrator_module, "interrupt", fake_interrupt)

    fake_manager = FakeMCPManager()
    fake_llm = FakeWorkflowLLM()
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(_make_hitl_config())
    await orchestrator.setup()
    response = await orchestrator.run("refund order 42", thread_id="t2")

    assert response == "Refund denied by user."
    assert fake_manager.tool_calls == []


@pytest.mark.asyncio
async def test_hitl_rejection_default_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """When interrupt omits 'response' the default cancellation message is used."""
    import gateway.core.orchestrator as orchestrator_module

    def fake_interrupt(value: dict[str, object]) -> dict[str, object]:
        return {"approved": False}

    monkeypatch.setattr(orchestrator_module, "interrupt", fake_interrupt)

    fake_manager = FakeMCPManager()
    fake_llm = FakeWorkflowLLM()
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(_make_hitl_config())
    await orchestrator.setup()
    response = await orchestrator.run("refund order 42", thread_id="t3")

    assert response == "Operation cancelled by user."
    assert fake_manager.tool_calls == []


@pytest.mark.asyncio
async def test_non_hitl_intent_skips_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Intents not in human_in_the_loop_intents should NOT call interrupt()."""
    import gateway.core.orchestrator as orchestrator_module

    calls: list[dict[str, object]] = []

    def fake_interrupt(value: dict[str, object]) -> dict[str, object]:
        calls.append(value)
        return {"approved": True}

    monkeypatch.setattr(orchestrator_module, "interrupt", fake_interrupt)

    fake_manager = FakeMCPManager()
    fake_llm = FakeWorkflowLLM()
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    # Config has HITL set to ["refund"] but the intent here is "lookup"
    orchestrator = GatewayOrchestrator(_make_hitl_config())
    await orchestrator.setup()

    # Monkey-patch the LLM to return "lookup" intent
    fake_llm.intent = "lookup"

    response = await orchestrator.run("lookup customer 99", thread_id="t4")

    assert response == "Found Customer Alice with ID 99"
    assert len(calls) == 0  # interrupt was NOT called
    assert fake_manager.tool_calls == [("db", "lookup_customer", {"customer_id": "99"})]


@pytest.mark.asyncio
async def test_resume_approves_hitl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Orchestrator.resume() method exists and accepts a thread_id + approval dict."""
    orchestrator = GatewayOrchestrator(_make_hitl_config())
    assert hasattr(orchestrator, "resume")


@pytest.mark.asyncio
async def test_hitl_proposed_tool_calls_in_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """The interrupt payload should list ALL proposed tool calls for the round."""
    import gateway.core.orchestrator as orchestrator_module

    interrupt_calls: list[dict[str, object]] = []

    def fake_interrupt(value: dict[str, object]) -> dict[str, object]:
        interrupt_calls.append(value)
        return {"approved": True}

    monkeypatch.setattr(orchestrator_module, "interrupt", fake_interrupt)

    fake_manager = FakeMCPManager()
    # Use a fake that returns multiple tool calls
    fake_llm = FakeWorkflowLLM(multi_tool=True)
    monkeypatch.setattr(orchestrator_module, "MCPConnectionManager", lambda: fake_manager)
    monkeypatch.setattr(orchestrator_module, "LLMClient", lambda config: fake_llm)

    orchestrator = GatewayOrchestrator(_make_hitl_config())
    await orchestrator.setup()
    await orchestrator.run("process multiple", thread_id="t5")

    assert len(interrupt_calls) == 1
    payload = interrupt_calls[0]
    proposed = payload["proposed_tool_calls"]
    assert len(proposed) == 2
    assert proposed[0] == {"name": "process_refund", "arguments": {"order_id": "42"}}
    assert proposed[1] == {
        "name": "send_notification",
        "arguments": {"message": "refund processed"},
    }


# ---------------------------------------------------------------------------
# Fixtures & test doubles
# ---------------------------------------------------------------------------


def _make_hitl_config() -> WorkflowConfig:
    """Build a workflow config with human_in_the_loop_intents set."""
    return WorkflowConfig(
        llm=LLMConfig(provider=LLMProvider.OPENAI, model_name="gpt-test"),
        mcp_servers=[
            MCPServerConfig(name="db", transport="http", url="http://localhost:8000/mcp"),
        ],
        intents=[
            IntentConfig(
                name="refund",
                description="Process billing refunds",
                mcp_server="db",
                system_prompt="Use refund tools.",
            ),
            IntentConfig(
                name="lookup",
                description="Lookup customer records",
                mcp_server="db",
                system_prompt="Use customer lookup tools.",
            ),
        ],
        human_in_the_loop_intents=["refund"],
    )


class FakeMCPManager:
    """Minimal MCP manager that exposes refund + lookup tools."""

    def __init__(self) -> None:
        self.registered: list[tuple[str, str, str | None, str | None, list[str]]] = []
        self.connected = False
        self.cleaned = False
        self.tool_calls: list[tuple[str, str, dict[str, object]]] = []

    def register(self, name: str, config: Any) -> None:
        self.registered.append((name, config.transport, config.url, config.command, config.args))

    async def connect_all(self) -> None:
        self.connected = True

    async def list_all_tools(self) -> dict[str, list[object]]:
        return {
            "db": [
                SimpleNamespace(
                    name="process_refund",
                    description="Process a refund for an order",
                    inputSchema={
                        "type": "object",
                        "properties": {"order_id": {"type": "string"}},
                        "required": ["order_id"],
                    },
                ),
                SimpleNamespace(
                    name="send_notification",
                    description="Send a notification",
                    inputSchema={
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                ),
                SimpleNamespace(
                    name="lookup_customer",
                    description="Lookup a customer",
                    inputSchema={
                        "type": "object",
                        "properties": {"customer_id": {"type": "string"}},
                        "required": ["customer_id"],
                    },
                ),
            ]
        }

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, object]
    ) -> str:
        self.tool_calls.append((server_name, tool_name, arguments))
        return f"Executed {tool_name}"

    async def cleanup_all(self) -> None:
        self.cleaned = True


class FakeWorkflowLLM:
    """Fake LLM that returns tool_calls or text depending on message history."""

    def __init__(self, multi_tool: bool = False) -> None:
        self.multi_tool = multi_tool
        self.intent = "refund"
        self.structured_calls: list[dict[str, object]] = []
        self.chat_calls: list[dict[str, object]] = []

    async def structured_output(
        self,
        messages: list[dict[str, str]],
        response_model: type,
    ) -> object:
        self.structured_calls.append({"messages": messages, "response_model": response_model})
        return response_model(intent=self.intent, confidence=0.95)

    async def chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> object:
        self.chat_calls.append({"messages": messages, "tools": tools})

        has_tool_role = any(m.get("role") == "tool" for m in messages)

        if not has_tool_role:
            # First call: return tool calls
            calls = []
            if self.intent == "lookup":
                calls.append(
                    SimpleNamespace(
                        id="call_0_lookup",
                        function=SimpleNamespace(
                            name="lookup_customer",
                            arguments='{"customer_id": "99"}',
                        ),
                    )
                )
            else:
                calls.append(
                    SimpleNamespace(
                        id="call_0_refund",
                        function=SimpleNamespace(
                            name="process_refund",
                            arguments='{"order_id": "42"}',
                        ),
                    )
                )
                if self.multi_tool:
                    calls.append(
                        SimpleNamespace(
                            id="call_1_notify",
                            function=SimpleNamespace(
                                name="send_notification",
                                arguments='{"message": "refund processed"}',
                            ),
                        )
                    )

            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=calls))]
            )

        # Second call (tool results present): synthesize text
        lookup = "Found Customer Alice with ID 99"
        refund = "Refund processed successfully."
        content = lookup if self.intent == "lookup" else refund
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))]
        )
