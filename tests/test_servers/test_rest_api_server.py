# SPDX-License-Identifier: Apache-2.0
"""Integration tests for the REST-to-MCP bridge server."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from gateway.mcp_client.http_client import MCPHttpClient


@pytest.mark.asyncio
async def test_rest_api_server_calls_get_and_post(rest_target_url: str) -> None:
    """REST bridge exposes call_api and permits GET/POST only."""
    port = 8802
    process = _start_server("servers/rest_api/server.py", {"MCP_PORT": str(port)})
    try:
        await _wait_for_tools(f"http://127.0.0.1:{port}/mcp", {"call_api"})

        async with MCPHttpClient(f"http://127.0.0.1:{port}/mcp") as client:
            get_response = await client.call_tool(
                "call_api",
                {"method": "GET", "url": f"{rest_target_url}/echo", "headers": {}, "body": None},
            )
            post_response = await client.call_tool(
                "call_api",
                {
                    "method": "POST",
                    "url": f"{rest_target_url}/echo",
                    "headers": {"X-Test": "yes"},
                    "body": {"hello": "world"},
                },
            )
            rejected = await client.call_tool(
                "call_api",
                {"method": "DELETE", "url": f"{rest_target_url}/echo", "headers": {}, "body": None},
            )

        assert '"method":"GET"' in get_response
        assert '"method":"POST"' in post_response
        assert '"hello":"world"' in post_response
        assert "Only GET and POST methods are allowed" in rejected
    finally:
        _stop_server(process)


@pytest.fixture()
async def rest_target_url(unused_tcp_port: int) -> AsyncIterator[str]:
    """Run a tiny local REST target for bridge tests."""

    async def echo(request: Request) -> JSONResponse:
        payload = await request.json() if request.method == "POST" else None
        return JSONResponse(
            {
                "method": request.method,
                "body": payload,
                "x_test": request.headers.get("x-test"),
            }
        )

    app = Starlette(routes=[Route("/echo", echo, methods=["GET", "POST"])])
    config = uvicorn.Config(app, host="127.0.0.1", port=unused_tcp_port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        yield f"http://127.0.0.1:{unused_tcp_port}"
    finally:
        server.should_exit = True
        await task


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


async def _port_is_ready(host: str, port: int) -> bool:
    """Return whether a TCP port accepts connections."""
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except OSError:
        return False
    writer.close()
    await writer.wait_closed()
    return True
