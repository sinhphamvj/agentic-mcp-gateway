# SPDX-License-Identifier: Apache-2.0
"""Integration tests for the filesystem MCP server."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gateway.mcp_client.http_client import MCPHttpClient


@pytest.mark.asyncio
async def test_filesystem_server_operates_under_allowed_root(tmp_path: Path) -> None:
    """Filesystem server lists, reads, searches, and blocks paths outside root."""
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    (allowed_root / "notes.txt").write_text("hello from notes", encoding="utf-8")
    (allowed_root / "data.json").write_text('{"ok": true}', encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    port = 8803
    process = _start_server(
        "servers/filesystem/server.py",
        {"ALLOWED_ROOT": str(allowed_root), "MCP_PORT": str(port)},
    )
    try:
        await _wait_for_tools(
            f"http://127.0.0.1:{port}/mcp",
            {"list_directory", "read_file", "search_files"},
        )

        async with MCPHttpClient(f"http://127.0.0.1:{port}/mcp") as client:
            entries = json.loads(await client.call_tool("list_directory", {"path": "."}))
            content = await client.call_tool("read_file", {"path": "notes.txt"})
            matches = json.loads(
                await client.call_tool("search_files", {"dir": ".", "pattern": "*.txt"})
            )
            rejected = await client.call_tool("read_file", {"path": str(outside)})

        assert entries == ["data.json", "notes.txt"]
        assert content == "hello from notes"
        assert matches == ["notes.txt"]
        assert "Path is outside ALLOWED_ROOT" in rejected
    finally:
        _stop_server(process)


def _start_server(script: str, env: dict[str, str]) -> subprocess.Popen[str]:
    """Start a server subprocess for integration testing."""
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.Popen(
        [sys.executable, script],
        cwd=Path(__file__).resolve().parents[2],
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


async def _wait_for_tools(url: str, expected_tools: set[str]) -> None:
    """Wait until the MCP server responds with expected tools."""
    deadline = time.monotonic() + 10
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if not await _port_is_ready("127.0.0.1", int(url.split(":")[-1].split("/")[0])):
            await asyncio.sleep(0.1)
            continue
        try:
            client = MCPHttpClient(url)
            try:
                await client.connect()
                tools = await client.list_tools()
            finally:
                await client.cleanup()
            names = {tool.name for tool in tools}
            if expected_tools.issubset(names):
                return
        except Exception as exc:  # pragma: no cover - diagnostic path
            last_error = exc
        await asyncio.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {url}: {last_error}")


async def _port_is_ready(host: str, port: int) -> bool:
    """Return whether a TCP port accepts connections."""
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except OSError:
        return False
    writer.close()
    await writer.wait_closed()
    return True


def _stop_server(process: subprocess.Popen[str]) -> None:
    """Terminate a server subprocess and surface stderr on failure."""
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    if process.returncode not in (0, -15):
        _, stderr = process.communicate()
        raise AssertionError(stderr)
