# SPDX-License-Identifier: Apache-2.0
"""Starlette HTTP server that drives a GatewayOrchestrator.

Exposes a minimal OpenAI-compatible surface:
- GET  /health                       → liveness probe
- POST /v1/chat/completions          → run one turn of the workflow

The shape of the chat-completions response is intentionally small and
incomplete relative to OpenAI's spec; only the fields real callers use
are present. The goal is "curl works" — not full API parity.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
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


def _last_user_message(messages: list[ChatMessage]) -> str:
    """Return the content of the most recent user-role message."""
    for msg in reversed(messages):
        if msg.role == "user" and msg.content:
            return msg.content
    return ""


async def health(_request: Request) -> JSONResponse:
    """Liveness probe."""
    return JSONResponse({"status": "ok"})


async def chat_completions(request: Request) -> JSONResponse:
    """Run one turn of the gateway workflow and return the response."""
    orchestrator: GatewayOrchestrator = request.app.state.orchestrator
    body = await request.json()
    payload = ChatCompletionRequest.model_validate(body)

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


def create_app(config_path: str) -> Starlette:
    """Build the Starlette app bound to a workflow config.

    Args:
        config_path: Path to a workflow.yaml file.

    Returns:
        A Starlette app with ``/health`` and ``/v1/chat/completions``
        routes, plus startup/shutdown hooks that initialise and tear
        down the orchestrator.
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
        ],
        lifespan=lifespan,
    )
    app.state.orchestrator = orchestrator  # type: ignore[attr-defined]
    return app
