# SPDX-License-Identifier: Apache-2.0
"""Integration tests for the SQLite MCP server."""

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
from servers.database.db_helper import create_sample_db


@pytest.mark.asyncio
async def test_database_server_lists_tables_and_runs_select(tmp_path: Path) -> None:
    """SQLite server exposes list_tables and SELECT-only query_database tools."""
    db_path = tmp_path / "sample.db"
    create_sample_db(db_path)

    port = 8800
    process = _start_server(
        "servers/database/server.py",
        {"DB_PATH": str(db_path), "MCP_PORT": str(port)},
    )
    try:
        await _wait_for_tools(f"http://127.0.0.1:{port}/mcp", {"list_tables", "query_database"})

        async with MCPHttpClient(f"http://127.0.0.1:{port}/mcp") as client:
            tables = json.loads(await client.call_tool("list_tables", {}))
            rows = json.loads(
                await client.call_tool(
                    "query_database",
                    {"sql": "SELECT name, email FROM users ORDER BY id"},
                )
            )
            rejected = await client.call_tool(
                "query_database",
                {"sql": "DELETE FROM users"},
            )

        assert tables == ["orders", "products", "users"]
        assert rows[0] == {"name": "Alice", "email": "alice@example.com"}
        assert "Only SELECT queries are allowed" in rejected
    finally:
        _stop_server(process)


def test_create_sample_db_has_expected_tables_and_rows(tmp_path: Path) -> None:
    """create_sample_db creates users, products, and orders with seed data."""
    import sqlite3

    db_path = tmp_path / "sample.db"
    create_sample_db(db_path)

    with sqlite3.connect(db_path) as connection:
        table_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        user_count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        product_count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        order_count = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

    assert [row[0] for row in table_rows] == ["orders", "products", "users"]
    assert user_count >= 2
    assert product_count >= 2
    assert order_count >= 2


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
