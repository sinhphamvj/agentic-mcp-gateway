# SPDX-License-Identifier: Apache-2.0
"""Workflow orchestration engine."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from gateway.core.llm_providers import LLMClient
from gateway.core.models import IntentConfig, WorkflowConfig
from gateway.core.router import UNKNOWN_INTENT, create_intent_classifier
from gateway.core.state import GatewayState
from gateway.mcp_client.manager import MCPConnectionManager, ServerConfig
from gateway.observability.tracer import setup_tracing

# Type alias for the union of checkpointers this orchestrator can hold.
# SqliteSaver is only available when the 'sqlite' extra is installed; it
# is referenced dynamically in ``_build_checkpointer`` so importing the
# type at module load time is intentionally avoided.
SqliteSaverHolder = Any


class GatewayOrchestrator:
    """LangGraph-powered orchestrator for multi-MCP agent workflows."""

    def __init__(self, config: WorkflowConfig) -> None:
        """Initialize the orchestrator.

        Args:
            config: Validated workflow configuration.
        """
        self.config = config
        self.llm_client = LLMClient(config.llm)
        self.mcp_manager = MCPConnectionManager()
        self.checkpointer: InMemorySaver | SqliteSaverHolder | None = None
        self.workflow: Any | None = None
        # Holds the SqliteSaver context manager so teardown() can close it.
        self._sqlite_cm: Any = None

    async def setup(self) -> None:
        """Register MCP servers, connect them, and compile the LangGraph workflow."""
        setup_tracing(enabled=self.config.enable_tracing)

        for server in self.config.mcp_servers:
            self.mcp_manager.register(
                server.name,
                ServerConfig(
                    name=server.name,
                    transport=server.transport,
                    url=server.url,
                    command=server.command,
                    args=server.args,
                ),
            )
        await self.mcp_manager.connect_all()

        graph = StateGraph(GatewayState)
        intent_to_node = {
            intent.name: self._agent_node_name(intent.name) for intent in self.config.intents
        }
        intent_to_node[UNKNOWN_INTENT] = "unknown_handler"

        graph.add_node(
            "intent_classifier",
            create_intent_classifier(self.llm_client, self.config.intents, intent_to_node),
            destinations=tuple(intent_to_node.values()),
        )
        graph.add_node("unknown_handler", self._unknown_handler)
        graph.add_node("compile_response", self._compile_response)

        for intent in self.config.intents:
            node_name = self._agent_node_name(intent.name)
            graph.add_node(node_name, self._create_agent_node(intent))
            graph.add_edge(node_name, "compile_response")

        graph.add_edge(START, "intent_classifier")
        graph.add_edge("unknown_handler", END)
        graph.add_edge("compile_response", END)

        self.checkpointer = self._build_checkpointer()
        self.workflow = graph.compile(checkpointer=self.checkpointer)

    def _build_checkpointer(self) -> InMemorySaver | Any:
        """Construct the checkpointer configured in the workflow YAML.

        Returns:
            An open ``BaseCheckpointSaver`` ready to be passed to
            ``StateGraph.compile``.
        """
        cfg = self.config.checkpointer
        if cfg.backend == "sqlite":
            try:
                from langgraph.checkpoint.sqlite import SqliteSaver
            except ImportError as exc:
                raise RuntimeError(
                    "SQLite checkpointer requires the 'sqlite' extra: "
                    "pip install 'agentic-mcp-gateway[sqlite]' or "
                    "uv add langgraph-checkpoint-sqlite"
                ) from exc
            path = cfg.path or "./gateway_state.db"
            self._sqlite_cm = SqliteSaver.from_conn_string(path)
            return self._sqlite_cm.__enter__()
        from langgraph.checkpoint.memory import InMemorySaver
        return InMemorySaver()

    def _create_agent_node(self, intent_cfg: IntentConfig) -> Any:
        """Create a LangGraph node that calls the LLM and optional MCP tools.

        Unlike the original single-call design, the node now runs up to
        ``max_tool_rounds`` LLM–tool cycles.  When the LLM requests a tool
        the node executes it, feeds the result back as a ``tool``-role
        message (OpenAI protocol), and lets the LLM produce a natural-language
        answer on the next turn.  The downstream ``_compile_response`` node
        passes the synthesised text through unchanged.
        """

        async def agent_node(state: GatewayState) -> dict[str, object]:
            tools_by_server = await self.mcp_manager.list_all_tools()
            server_tools = tools_by_server.get(intent_cfg.mcp_server, [])
            openai_tools = [_tool_to_openai(tool) for tool in server_tools]
            messages = _state_messages_to_openai(state.get("messages", []))
            if intent_cfg.system_prompt:
                messages.insert(0, {"role": "system", "content": intent_cfg.system_prompt})

            max_rounds = self.config.max_tool_rounds

            for _round in range(max_rounds):
                response = await self.llm_client.chat(messages, tools=openai_tools)
                message = _first_response_message(response)
                tool_calls = _message_tool_calls(message)

                if not tool_calls:
                    return {
                        "active_server": intent_cfg.mcp_server,
                        "response": _message_content(message),
                        "tool_results": [],
                    }

                parsed_calls: list[dict[str, object]] = []
                for tc in tool_calls:
                    name, args = _parse_tool_call(tc)
                    tc_id = getattr(tc, "id", f"call_{_round}_{name}")
                    parsed_calls.append({"id": tc_id, "name": name, "arguments": args, "raw": tc})

                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": pc["id"],
                            "type": "function",
                            "function": {
                                "name": pc["name"],
                                "arguments": json.dumps(pc["arguments"]),  # type: ignore[arg-type]
                            },
                        }
                        for pc in parsed_calls
                    ],
                })

                for pc in parsed_calls:
                    result = await self.mcp_manager.call_tool(
                        intent_cfg.mcp_server,
                        str(pc["name"]),
                        dict(pc["arguments"]),  # type: ignore[call-overload]
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": str(pc["id"]),
                        "content": json.dumps(result) if isinstance(result, dict) else str(result),
                    })

            return {
                "active_server": intent_cfg.mcp_server,
                "response": "Max tool rounds reached.",
                "tool_results": [],
            }

        return agent_node

    async def _unknown_handler(self, state: GatewayState) -> dict[str, object]:
        """Pause for human input when the classifier cannot route the request."""
        human_response = interrupt(
            {
                "reason": "Unknown intent",
                "message": _last_message_text(state.get("messages", [])),
                "metadata": state.get("metadata", {}),
            }
        )
        return {"response": str(human_response)}

    async def _compile_response(self, state: GatewayState) -> dict[str, str]:
        """Format the final response.

        If the agent node already produced a synthesised response (F2) it
        is passed through unchanged.  Otherwise the original string-join of
        ``tool_results`` is used as a fallback.
        """
        existing = state.get("response")
        if existing:
            return {"response": existing}
        tool_results = state.get("tool_results", [])
        if not tool_results:
            return {"response": "No results."}

        lines: list[str] = []
        for result in tool_results:
            tool_name = str(result.get("tool", ""))
            result_text = str(result.get("result", ""))
            if tool_name:
                lines.append(f"{tool_name}: {result_text}")
            else:
                lines.append(result_text)
        return {"response": "\n".join(lines)}

    async def run(self, user_message: str, thread_id: str) -> str:
        """Run the workflow for one user message.

        Args:
            user_message: User input to route and execute.
            thread_id: LangGraph checkpoint thread identifier.

        Returns:
            Final response text.
        """
        if self.workflow is None:
            await self.setup()

        initial_state: GatewayState = {
            "messages": [{"role": "user", "content": user_message}],
            "intent": "",
            "active_server": "",
            "tool_results": [],
            "response": "",
            "metadata": {},
        }
        assert self.workflow is not None
        result = await self.workflow.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": thread_id}},
        )
        return str(result.get("response", ""))

    async def teardown(self) -> None:
        """Clean up all MCP connections and close the checkpointer."""
        await self.mcp_manager.cleanup_all()
        if self._sqlite_cm is not None:
            self._sqlite_cm.__exit__(None, None, None)
            self._sqlite_cm = None
            self.checkpointer = None

    @staticmethod
    def _agent_node_name(intent_name: str) -> str:
        """Return the graph node name for an intent."""
        return f"agent_{intent_name}"


def _tool_to_openai(tool: object) -> dict[str, object]:
    """Convert an MCP tool description to OpenAI tool-call format."""
    input_schema = _get_value(tool, "inputSchema", "input_schema", default=None)
    if input_schema is None:
        input_schema = {"type": "object", "properties": {}}

    return {
        "type": "function",
        "function": {
            "name": str(_get_value(tool, "name", default="")),
            "description": str(_get_value(tool, "description", default="")),
            "parameters": input_schema,
        },
    }


def _first_response_message(response: object) -> object:
    """Extract the first assistant message from a chat response."""
    choices = _get_value(response, "choices", default=None)
    if choices:
        first_choice = choices[0]
        return _get_value(first_choice, "message", default=first_choice)
    return response


def _message_tool_calls(message: object) -> Sequence[object]:
    """Extract tool calls from a response message."""
    tool_calls = _get_value(message, "tool_calls", default=None)
    return tool_calls or []


def _parse_tool_call(tool_call: object) -> tuple[str, dict[str, object]]:
    """Parse a model tool call into a tool name and argument dict."""
    function = _get_value(tool_call, "function", default={})
    tool_name = str(_get_value(function, "name", default=""))
    raw_arguments = _get_value(function, "arguments", default={})
    if isinstance(raw_arguments, str):
        try:
            parsed_arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            parsed_arguments = {}
    elif isinstance(raw_arguments, dict):
        parsed_arguments = raw_arguments
    else:
        parsed_arguments = {}
    return tool_name, parsed_arguments


def _message_content(message: object) -> str:
    """Extract text content from a response message."""
    return str(_get_value(message, "content", default=""))


def _state_messages_to_openai(messages: Sequence[object]) -> list[dict[str, object]]:
    """Normalize state messages to OpenAI-style dicts."""
    return [_message_to_openai(message) for message in messages]


def _message_to_openai(message: object) -> dict[str, object]:
    """Normalize one state message to an OpenAI-style dict."""
    if isinstance(message, dict):
        return {
            "role": str(message.get("role", "user")),
            "content": str(message.get("content", "")),
        }

    message_type = str(_get_value(message, "type", "role", default="user"))
    role_map = {"human": "user", "ai": "assistant"}
    return {
        "role": role_map.get(message_type, message_type),
        "content": str(_get_value(message, "content", default=message)),
    }


def _last_message_text(messages: Sequence[object]) -> str:
    """Return text from the most recent state message."""
    if not messages:
        return ""
    return str(_message_to_openai(messages[-1])["content"])


def _get_value(item: object, *names: str, default: Any = None) -> Any:
    """Get the first named value from either a dict or object."""
    for name in names:
        if isinstance(item, dict) and name in item:
            return item[name]
        if hasattr(item, name):
            return getattr(item, name)
    return default
