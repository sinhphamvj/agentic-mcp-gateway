# SPDX-License-Identifier: Apache-2.0
"""Tests for the HTTP server (F1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from gateway.core.orchestrator import GatewayOrchestrator
from gateway.server.app import create_app

REPO_ROOT = Path(__file__).parent.parent
WORKFLOW_PATH = REPO_ROOT / "workflow.yaml"


@pytest.fixture
def mock_orchestrator() -> GatewayOrchestrator:
    """Return a GatewayOrchestrator with all async methods stubbed out.

    The app fixture installs this on app.state so the request handlers
    use the mock instead of trying to connect to real MCP servers.
    """
    orch = MagicMock()
    orch.setup = AsyncMock()
    orch.teardown = AsyncMock()
    orch.run = AsyncMock(return_value="mocked assistant reply")
    return orch


def _build_app_with_mock(orchestrator: GatewayOrchestrator) -> tuple[TestClient, object]:
    """Build a TestClient whose app.state.orchestrator is the given mock.

    We bypass create_app's real-config path by importing the app builder
    and overriding state.orchestrator before any request fires.
    """
    from gateway.server.app import create_app as _create_app

    # We need a real config to satisfy create_app; use the repo's
    # workflow.yaml. The real GatewayOrchestrator constructed inside
    # create_app is replaced on app.state before startup runs.
    app = _create_app(str(WORKFLOW_PATH))
    app.state.orchestrator = orchestrator  # type: ignore[attr-defined]
    return TestClient(app, raise_server_exceptions=True), app


def test_create_app_returns_starlette() -> None:
    """create_app should produce a Starlette instance with the expected routes."""
    app = create_app(str(WORKFLOW_PATH))
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/health" in paths
    assert "/v1/chat/completions" in paths


def test_health_endpoint(mock_orchestrator: GatewayOrchestrator) -> None:
    """GET /health should return 200 with status=ok."""
    client, _app = _build_app_with_mock(mock_orchestrator)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_completions_calls_orchestrator(mock_orchestrator: GatewayOrchestrator) -> None:
    """POST /v1/chat/completions should call orchestrator.run with the user message."""
    client, _app = _build_app_with_mock(mock_orchestrator)
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "What tables are in the DB?"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["message"]["content"] == "mocked assistant reply"
    mock_orchestrator.run.assert_awaited_once()  # type: ignore[attr-defined]
    _args, kwargs = mock_orchestrator.run.call_args  # type: ignore[attr-defined]
    assert kwargs["user_message"] == "What tables are in the DB?"
    assert kwargs["thread_id"] == "default"


def test_chat_completions_thread_id_propagates(mock_orchestrator: GatewayOrchestrator) -> None:
    """The thread_id in the request body should be forwarded to orchestrator.run."""
    client, _app = _build_app_with_mock(mock_orchestrator)
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "thread_id": "user-42",
        },
    )
    assert response.status_code == 200
    _args, kwargs = mock_orchestrator.run.call_args  # type: ignore[attr-defined]
    assert kwargs["thread_id"] == "user-42"


def test_chat_completions_rejects_empty_messages(mock_orchestrator: GatewayOrchestrator) -> None:
    """A request with no user message should return 400 and not call the orchestrator."""
    client, _app = _build_app_with_mock(mock_orchestrator)
    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "system", "content": "you are helpful"}]},
    )
    assert response.status_code == 400
    assert "error" in response.json()
    mock_orchestrator.run.assert_not_called()  # type: ignore[attr-defined]


def test_chat_completions_uses_last_user_message(mock_orchestrator: GatewayOrchestrator) -> None:
    """When multiple user messages are present, the most recent one is used."""
    client, _app = _build_app_with_mock(mock_orchestrator)
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "first answer"},
                {"role": "user", "content": "second question"},
            ],
        },
    )
    assert response.status_code == 200
    _args, kwargs = mock_orchestrator.run.call_args  # type: ignore[attr-defined]
    assert kwargs["user_message"] == "second question"
