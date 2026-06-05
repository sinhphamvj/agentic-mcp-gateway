# SPDX-License-Identifier: Apache-2.0
"""LangGraph state schema definitions."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class GatewayState(TypedDict):
    """State flowing through the gateway workflow graph."""

    messages: Annotated[list, add_messages]
    intent: str
    active_server: str
    tool_results: list[dict[str, Any]]
    response: str
    metadata: dict[str, Any]
