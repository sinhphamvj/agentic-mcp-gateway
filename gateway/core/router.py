# SPDX-License-Identifier: Apache-2.0
"""Intent routing logic for gateway workflows."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from langgraph.types import Command
from pydantic import BaseModel, create_model

from gateway.core.models import IntentConfig
from gateway.core.state import GatewayState
from gateway.observability.tracer import trace_router_decision

UNKNOWN_INTENT = "UNKNOWN"


def build_intent_model(intents: Sequence[IntentConfig]) -> type[BaseModel]:
    """Build a Pydantic model whose intent is limited to configured routes.

    Args:
        intents: Workflow intent configurations.

    Returns:
        Dynamic Pydantic model with ``intent`` and ``confidence`` fields.

    Raises:
        ValueError: If no intents are configured.
    """
    if not intents:
        raise ValueError("Intent classifier requires at least one intent.")

    allowed_intents = tuple(intent.name for intent in intents) + (UNKNOWN_INTENT,)
    intent_literal = Literal.__getitem__(allowed_intents)
    return create_model(
        "IntentClassification",
        intent=(intent_literal, ...),
        confidence=(float, ...),
    )


def create_intent_classifier(
    llm_client: Any,
    intents: Sequence[IntentConfig],
    intent_to_node: dict[str, str],
) -> Any:
    """Create a LangGraph node that routes by structured intent classification."""
    response_model = build_intent_model(intents)
    intents_by_name = {intent.name: intent for intent in intents}

    async def classify_intent(state: GatewayState) -> Command:
        """Classify the current user request and route to the target node."""
        messages = [
            {"role": "system", "content": _classifier_prompt(intents)},
            *_messages_to_openai(state.get("messages", [])),
        ]
        classification = await llm_client.structured_output(messages, response_model)
        intent_name = classification.intent
        if intent_name not in intent_to_node:
            intent_name = UNKNOWN_INTENT

        with trace_router_decision(intent_name, classification.confidence):
            metadata = dict(state.get("metadata", {}))
            metadata["confidence"] = classification.confidence
            intent_config = intents_by_name.get(intent_name)
            active_server = intent_config.mcp_server if intent_config else ""
            target_node = intent_to_node.get(intent_name, intent_to_node[UNKNOWN_INTENT])

        return Command(
            goto=target_node,
            update={
                "intent": intent_name,
                "active_server": active_server,
                "metadata": metadata,
            },
        )

    return classify_intent


def _classifier_prompt(intents: Sequence[IntentConfig]) -> str:
    """Create the system prompt used for intent classification."""
    intent_lines = "\n".join(f"- {intent.name}: {intent.description}" for intent in intents)
    return (
        "Classify the user's request into one configured intent. "
        f"Use {UNKNOWN_INTENT} if none match.\n\nIntents:\n{intent_lines}"
    )


def _messages_to_openai(messages: Sequence[object]) -> list[dict[str, str]]:
    """Normalize LangChain/LangGraph or dict messages to OpenAI-style dicts."""
    return [_message_to_openai(message) for message in messages]


def _message_to_openai(message: object) -> dict[str, str]:
    """Normalize one message to an OpenAI-style dict."""
    if isinstance(message, dict):
        role = str(message.get("role", "user"))
        content = str(message.get("content", ""))
        return {"role": role, "content": content}

    message_type = str(getattr(message, "type", getattr(message, "role", "user")))
    role_map = {"human": "user", "ai": "assistant"}
    role = role_map.get(message_type, message_type)
    content = str(getattr(message, "content", message))
    return {"role": role, "content": content}
