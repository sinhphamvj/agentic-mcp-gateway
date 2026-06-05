# SPDX-License-Identifier: Apache-2.0
"""Low-level MCP filesystem server exposed over Streamable HTTP."""

from __future__ import annotations

import contextlib
import json
import os
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

MAX_READ_BYTES = 100 * 1024
server = Server("agentic-mcp-gateway-filesystem", version="0.1.0")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List filesystem tools."""
    return [
        Tool(
            name="list_directory",
            description="List entries in a directory under ALLOWED_ROOT.",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        Tool(
            name="read_file",
            description="Read a text file under ALLOWED_ROOT, up to 100KB.",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        Tool(
            name="search_files",
            description="Search for files under ALLOWED_ROOT using a glob pattern.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dir": {"type": "string"},
                    "pattern": {"type": "string"},
                },
                "required": ["dir", "pattern"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch filesystem tool calls."""
    if name == "list_directory":
        result = list_directory(str(arguments.get("path", ".")))
    elif name == "read_file":
        result = read_file(str(arguments.get("path", "")))
    elif name == "search_files":
        result = search_files(
            directory=str(arguments.get("dir", ".")),
            pattern=str(arguments.get("pattern", "*")),
        )
    else:
        result = f"Unknown tool: {name}"
    return [TextContent(type="text", text=result)]


def list_directory(path: str) -> str:
    """List directory entries as JSON."""
    try:
        directory = _safe_path(path)
        if not directory.is_dir():
            return f"Not a directory: {path}"
        return json.dumps(sorted(child.name for child in directory.iterdir()), ensure_ascii=False)
    except ValueError as exc:
        return str(exc)


def read_file(path: str) -> str:
    """Read a UTF-8 text file capped at 100KB."""
    try:
        file_path = _safe_path(path)
        if not file_path.is_file():
            return f"Not a file: {path}"
        if file_path.stat().st_size > MAX_READ_BYTES:
            return "File exceeds 100KB limit."
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "File is not valid UTF-8 text."
    except ValueError as exc:
        return str(exc)


def search_files(directory: str, pattern: str) -> str:
    """Search for files below a directory using a glob pattern."""
    try:
        root = _safe_path(directory)
        if not root.is_dir():
            return f"Not a directory: {directory}"
        matches = [
            str(match.relative_to(_allowed_root()))
            for match in root.rglob(pattern)
            if match.is_file() and _is_under_allowed_root(match)
        ]
        return json.dumps(sorted(matches), ensure_ascii=False)
    except ValueError as exc:
        return str(exc)


def create_app() -> Starlette:
    """Create the Starlette app exposing the MCP endpoint."""
    session_manager = StreamableHTTPSessionManager(app=server, stateless=True, json_response=True)
    mcp_app = StreamableHTTPASGIApp(session_manager)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    return Starlette(routes=[Route("/mcp", endpoint=mcp_app)], lifespan=lifespan)


def main() -> None:
    """Run the filesystem MCP server."""
    port = int(os.environ.get("MCP_PORT", "8003"))
    uvicorn.run(create_app(), host="127.0.0.1", port=port)


def _allowed_root() -> Path:
    """Return the resolved allowed filesystem root."""
    return Path(os.environ.get("ALLOWED_ROOT", ".")).resolve()


def _safe_path(path: str) -> Path:
    """Resolve a path and ensure it stays under ALLOWED_ROOT."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = _allowed_root() / candidate
    resolved = candidate.resolve()
    if not _is_under_allowed_root(resolved):
        raise ValueError("Path is outside ALLOWED_ROOT.")
    return resolved


def _is_under_allowed_root(path: Path) -> bool:
    """Return whether path is within ALLOWED_ROOT."""
    allowed_root = _allowed_root()
    try:
        path.resolve().relative_to(allowed_root)
    except ValueError:
        return False
    return True


class StreamableHTTPASGIApp:
    """ASGI wrapper for the MCP Streamable HTTP session manager."""

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self.session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.session_manager.handle_request(scope, receive, send)


if __name__ == "__main__":
    main()
