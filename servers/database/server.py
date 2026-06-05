# SPDX-License-Identifier: Apache-2.0
"""Low-level MCP SQLite server exposed over Streamable HTTP."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

try:
    from servers.database.db_helper import create_sample_db
except ImportError:  # pragma: no cover - supports running from this directory
    from db_helper import create_sample_db


server = Server("agentic-mcp-gateway-database", version="0.1.0")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List SQLite tools."""
    return [
        Tool(
            name="query_database",
            description="Run a read-only SELECT query against the SQLite database.",
            inputSchema={
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        ),
        Tool(
            name="list_tables",
            description="List user tables in the SQLite database.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch SQLite tool calls."""
    if name == "query_database":
        result = query_database(str(arguments.get("sql", "")))
    elif name == "list_tables":
        result = list_database_tables()
    else:
        result = f"Unknown tool: {name}"
    return [TextContent(type="text", text=result)]


def query_database(sql: str) -> str:
    """Run a SELECT query and return JSON rows."""
    if not sql.strip().lower().startswith("select"):
        return "Only SELECT queries are allowed."

    try:
        with _connect() as connection:
            rows = connection.execute(sql).fetchall()
            return json.dumps([dict(row) for row in rows], ensure_ascii=False)
    except sqlite3.Error as exc:
        return f"Database error: {exc}"


def list_database_tables() -> str:
    """Return JSON list of SQLite user tables."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
    return json.dumps([row["name"] for row in rows], ensure_ascii=False)


def create_app() -> Starlette:
    """Create the Starlette app exposing the MCP endpoint."""
    _ensure_database_exists()
    session_manager = StreamableHTTPSessionManager(app=server, stateless=True, json_response=True)
    mcp_app = StreamableHTTPASGIApp(session_manager)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    return Starlette(routes=[Route("/mcp", endpoint=mcp_app)], lifespan=lifespan)


def main() -> None:
    """Run the SQLite MCP server."""
    port = int(os.environ.get("MCP_PORT", "8000"))
    uvicorn.run(create_app(), host="127.0.0.1", port=port)


def _connect() -> sqlite3.Connection:
    """Connect to the configured SQLite database."""
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    return connection


def _db_path() -> Path:
    """Return configured database path."""
    return Path(os.environ.get("DB_PATH", "sample.db"))


def _ensure_database_exists() -> None:
    """Create a sample database if the configured path does not exist."""
    path = _db_path()
    if not path.exists():
        create_sample_db(path)


class StreamableHTTPASGIApp:
    """ASGI wrapper for the MCP Streamable HTTP session manager."""

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self.session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.session_manager.handle_request(scope, receive, send)


if __name__ == "__main__":
    main()
