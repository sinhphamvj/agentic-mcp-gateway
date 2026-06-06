# SPDX-License-Identifier: Apache-2.0
"""Starlette HTTP server that drives a GatewayOrchestrator.

Exposes a minimal OpenAI-compatible surface:
- GET  /health                               → liveness probe
- POST /v1/chat/completions                  → run one turn of the workflow
- POST /v1/threads/{thread_id}/resume        → resume a paused HITL thread

The shape of the chat-completions response is intentionally small and
incomplete relative to OpenAI's spec; only the fields real callers use
are present. The goal is "curl works" — not full API parity.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from gateway.core.config import load_config
from gateway.core.orchestrator import GatewayOrchestrator


class ChatMessage(BaseModel):
    """One message in a chat-completions request."""

    role: str
    content: str = ""


class ChatCompletionRequest(BaseModel):
    """Request body for POST /v1/chat/completions."""

    messages: list[ChatMessage]
    thread_id: str = Field(default="default", description="LangGraph thread identifier.")
    stream: bool = Field(default=False, description="Reserved for F9; always false for now.")


class ChatChoice(BaseModel):
    """One choice in a chat-completions response."""

    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    """Response body for POST /v1/chat/completions."""

    id: str
    object: str = "chat.completion"
    choices: list[ChatChoice]


class ResumeRequest(BaseModel):
    """Request body for POST /v1/threads/{thread_id}/resume.

    The body is forwarded to LangGraph's ``Command(resume=...)``.  For
    human-in-the-loop gates, the agent node checks
    ``approval["approved"]`` and, when ``False``, reads
    ``approval.get("response", "Operation cancelled by user.")``.
    Extra fields are ignored.
    """

    approved: bool = True
    response: str | None = None


class ResumeResponse(BaseModel):
    """Response body for POST /v1/threads/{thread_id}/resume."""

    id: str
    object: str = "thread.resume"
    thread_id: str
    response: str


def _last_user_message(messages: list[ChatMessage]) -> str:
    """Return the content of the most recent user-role message."""
    for msg in reversed(messages):
        if msg.role == "user" and msg.content:
            return msg.content
    return ""


async def health(request: Request) -> JSONResponse:
    """Liveness probe with per-MCP-server status."""
    orchestrator: GatewayOrchestrator = request.app.state.orchestrator
    mcp_status = orchestrator.mcp_manager.get_health()
    overall = (
        "ok"
        if all(info.get("status") == "connected" for info in mcp_status.values())
        else "degraded"
    )
    return JSONResponse({"status": overall, "mcp_servers": mcp_status})


async def _stream_response(
    request: Request,
    messages: list[dict[str, object]],
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted chunks from the LLM."""
    orchestrator: GatewayOrchestrator = request.app.state.orchestrator
    llm_client = orchestrator.llm_client

    # First chunk: set the role
    yield (
        "data: "
        + json.dumps(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": None,
                    }
                ],
                "object": "chat.completion.chunk",
            }
        )
        + "\n\n"
    )

    async for event_type, data in llm_client.stream_chat(messages):
        if event_type == "delta":
            yield (
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": data},
                                "finish_reason": None,
                            }
                        ],
                        "object": "chat.completion.chunk",
                    }
                )
                + "\n\n"
            )
        elif event_type == "tool_call":
            yield (
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"tool_calls": data},
                                "finish_reason": None,
                            }
                        ],
                        "object": "chat.completion.chunk",
                    }
                )
                + "\n\n"
            )
        elif event_type == "usage":
            yield (
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": None,
                            }
                        ],
                        "object": "chat.completion.chunk",
                        "usage": data,
                    }
                )
                + "\n\n"
            )
        elif event_type == "done":
            # Final chunk with finish_reason
            yield (
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop",
                            }
                        ],
                        "object": "chat.completion.chunk",
                    }
                )
                + "\n\n"
            )
            yield "data: [DONE]\n\n"


async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
    """Run one turn of the gateway workflow and return the response."""
    orchestrator: GatewayOrchestrator = request.app.state.orchestrator
    body = await request.json()
    payload = ChatCompletionRequest.model_validate(body)

    if payload.stream:
        messages_dicts = [m.model_dump() for m in payload.messages]
        return StreamingResponse(
            _stream_response(request, messages_dicts),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    user_message = _last_user_message(payload.messages)
    if not user_message:
        return JSONResponse(
            {"error": {"message": "No user message provided.", "type": "invalid_request"}},
            status_code=400,
        )

    response_text = await orchestrator.run(
        user_message=user_message,
        thread_id=payload.thread_id,
    )

    return JSONResponse(
        ChatCompletionResponse(
            id=f"chatcmpl-{payload.thread_id}",
            choices=[
                ChatChoice(
                    message=ChatMessage(role="assistant", content=response_text),
                ),
            ],
        ).model_dump()
    )


async def resume_thread(request: Request) -> JSONResponse:
    """Resume a paused workflow thread.

    The body is forwarded to ``GatewayOrchestrator.resume``, which feeds
    it to ``Command(resume=...)``.  For HITL pauses the agent node
    expects ``{"approved": True}`` (continue) or
    ``{"approved": False, "response": "..."}`` (cancel).
    """
    orchestrator: GatewayOrchestrator = request.app.state.orchestrator
    thread_id = request.path_params["thread_id"]

    raw_body = await request.json()
    if not isinstance(raw_body, dict):
        return JSONResponse(
            {
                "error": {
                    "message": "Request body must be a JSON object.",
                    "type": "invalid_request",
                }
            },
            status_code=400,
        )

    payload = ResumeRequest.model_validate(raw_body)
    action: dict[str, Any] = {"approved": payload.approved}
    if payload.response is not None:
        action["response"] = payload.response

    response_text = await orchestrator.resume(thread_id, action)

    return JSONResponse(
        ResumeResponse(
            id=f"resume-{thread_id}",
            thread_id=thread_id,
            response=response_text,
        ).model_dump()
    )


def create_app(config_path: str) -> Starlette:
    """Build the Starlette app bound to a workflow config.

    Args:
        config_path: Path to a workflow.yaml file.

    Returns:
        A Starlette app with ``/health``, ``/v1/chat/completions``, and
        ``/v1/threads/{thread_id}/resume`` routes, plus startup/shutdown
        hooks that initialise and tear down the orchestrator.
    """
    config = load_config(config_path)
    orchestrator = GatewayOrchestrator(config)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        await orchestrator.setup()
        try:
            yield
        finally:
            await orchestrator.teardown()

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
        lifespan=lifespan,
    )
    app.state.orchestrator = orchestrator  # type: ignore[attr-defined]
    return app
