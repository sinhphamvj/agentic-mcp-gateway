# SPDX-License-Identifier: Apache-2.0
"""Tests for LangGraph intent routing helpers."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gateway.core.models import IntentConfig
from gateway.core.router import build_intent_model, create_intent_classifier


def test_build_intent_model_accepts_configured_intents_and_unknown() -> None:
    """Dynamic intent model uses a Literal of configured intent names plus UNKNOWN."""
    model = build_intent_model(
        [
            IntentConfig(name="lookup", description="Lookup records", mcp_server="db"),
            IntentConfig(name="deploy", description="Deploy services", mcp_server="ops"),
        ]
    )

    lookup = model(intent="lookup", confidence=0.91)
    unknown = model(intent="UNKNOWN", confidence=0.12)

    assert lookup.intent == "lookup"
    assert lookup.confidence == 0.91
    assert unknown.intent == "UNKNOWN"
    with pytest.raises(ValidationError):
        model(intent="refund", confidence=0.5)


def test_build_intent_model_requires_at_least_one_intent() -> None:
    """Intent model creation rejects empty workflow intent lists."""
    with pytest.raises(ValueError, match="at least one intent"):
        build_intent_model([])


async def test_intent_classifier_routes_known_intent_to_target_node() -> None:
    """Classifier returns a Command pointing at the node mapped to the intent."""
    intents = [
        IntentConfig(name="lookup", description="Lookup records", mcp_server="db"),
        IntentConfig(name="deploy", description="Deploy services", mcp_server="ops"),
    ]
    llm = FakeStructuredLLM(intent="lookup", confidence=0.87)
    classifier = create_intent_classifier(
        llm,
        intents,
        {"lookup": "agent_lookup", "deploy": "agent_deploy", "UNKNOWN": "unknown_handler"},
    )

    command = await classifier({"messages": [{"role": "user", "content": "find customer 42"}]})

    assert command.goto == "agent_lookup"
    assert command.update["intent"] == "lookup"
    assert command.update["active_server"] == "db"
    assert command.update["metadata"] == {"confidence": 0.87}
    assert llm.response_model.__name__ == "IntentClassification"
    assert "Lookup records" in llm.messages[0]["content"]


async def test_intent_classifier_routes_unknown_intent_to_unknown_handler() -> None:
    """Classifier routes UNKNOWN to the configured unknown handler."""
    intents = [IntentConfig(name="lookup", description="Lookup records", mcp_server="db")]
    llm = FakeStructuredLLM(intent="UNKNOWN", confidence=0.21)
    classifier = create_intent_classifier(
        llm,
        intents,
        {"lookup": "agent_lookup", "UNKNOWN": "unknown_handler"},
    )

    command = await classifier({"messages": [{"role": "user", "content": "do something odd"}]})

    assert command.goto == "unknown_handler"
    assert command.update["intent"] == "UNKNOWN"
    assert command.update["active_server"] == ""
    assert command.update["metadata"] == {"confidence": 0.21}


class FakeStructuredLLM:
    """Fake structured-output client for classifier tests."""

    def __init__(self, intent: str, confidence: float) -> None:
        self.intent = intent
        self.confidence = confidence
        self.messages: list[dict[str, str]] = []
        self.response_model: type | None = None

    async def structured_output(
        self,
        messages: list[dict[str, str]],
        response_model: type,
    ) -> object:
        """Return a response-model instance with the configured classification."""
        self.messages = messages
        self.response_model = response_model
        return response_model(intent=self.intent, confidence=self.confidence)
