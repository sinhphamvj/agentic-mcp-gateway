# SPDX-License-Identifier: Apache-2.0
"""Tests for OpenClaw-compatible skill generation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from gateway.cli import main
from gateway.skills.generator import generate_skill_md


async def test_generate_skill_md_lists_tools_and_writes_skill_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """generate_skill_md connects to MCP, renders tools, and writes SKILL.md."""
    import gateway.skills.generator as generator_module

    monkeypatch.setattr(generator_module, "MCPHttpClient", fake_mcp_client_factory)

    content = await generate_skill_md(
        server_url="http://localhost:8000/mcp",
        skill_name="database",
        skill_description="Query a database",
        gateway_endpoint="http://localhost:8001/generate",
        output_dir=tmp_path,
    )

    skill_path = tmp_path / "database" / "SKILL.md"
    assert skill_path.read_text(encoding="utf-8") == content
    assert content.startswith("---\nname: database\ndescription: Query a database\n---")
    assert "- **query_database**: Run a SELECT query." in content
    assert "- **list_tables**: List tables." in content
    assert "curl -X POST http://localhost:8001/generate" in content
    assert '"input_message": "<query>"' in content


def test_cli_skills_generate_writes_skill_file(tmp_path: Path, monkeypatch) -> None:
    """amcpg skills generate delegates to the async generator."""
    import gateway.cli as cli_module

    async def fake_generate_skill_md(
        server_url: str,
        skill_name: str,
        skill_description: str,
        gateway_endpoint: str = "http://localhost:8001/generate",
        output_dir: Path | None = None,
    ) -> str:
        assert server_url == "http://localhost:8000/mcp"
        assert skill_name == "test"
        assert skill_description == "test"
        assert gateway_endpoint == "http://localhost:8001/generate"
        assert output_dir == tmp_path
        skill_dir = tmp_path / "test"
        skill_dir.mkdir(parents=True)
        skill_path = skill_dir / "SKILL.md"
        content = "---\nname: test\ndescription: test\n---\n"
        skill_path.write_text(content, encoding="utf-8")
        return content

    monkeypatch.setattr(cli_module, "generate_skill_md", fake_generate_skill_md)

    result = CliRunner().invoke(
        main,
        [
            "skills",
            "generate",
            "--server-url",
            "http://localhost:8000/mcp",
            "--output-dir",
            str(tmp_path),
            "--name",
            "test",
            "--desc",
            "test",
        ],
    )

    assert result.exit_code == 0
    assert "Wrote" in result.output
    assert (tmp_path / "test" / "SKILL.md").exists()


def test_cli_openclaw_setup_generates_soul_and_skills(tmp_path: Path, monkeypatch) -> None:
    """openclaw-setup reads workflow YAML and generates SOUL.md plus SKILL files."""
    import gateway.cli as cli_module

    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(
        """
llm:
  provider: openai
  model_name: gpt-test
mcp_servers:
  - name: database
    transport: http
    url: http://localhost:8000/mcp
    description: Query databases
  - name: rest
    transport: http
    url: http://localhost:8002/mcp
    description: Call REST APIs
intents:
  - name: lookup
    description: Lookup records
    mcp_server: database
gateway_port: 9001
""",
        encoding="utf-8",
    )

    async def fake_generate_skill_md(
        server_url: str,
        skill_name: str,
        skill_description: str,
        gateway_endpoint: str = "http://localhost:8001/generate",
        output_dir: Path | None = None,
    ) -> str:
        assert output_dir is not None
        skill_dir = output_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        content = f"---\nname: {skill_name}\ndescription: {skill_description}\n---\n{server_url}\n"
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        return content

    monkeypatch.setattr(cli_module, "generate_skill_md", fake_generate_skill_md)

    result = CliRunner().invoke(
        main,
        ["skills", "openclaw-setup", "--config", str(config_path), "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert (tmp_path / "SOUL.md").exists()
    assert (tmp_path / "database" / "SKILL.md").exists()
    assert (tmp_path / "rest" / "SKILL.md").exists()
    soul = (tmp_path / "SOUL.md").read_text(encoding="utf-8")
    assert "agentic-mcp-gateway" in soul
    assert "database" in soul
    assert "rest" in soul


def fake_mcp_client_factory(server_url: str) -> object:
    """Create a fake MCP client context manager."""
    assert server_url == "http://localhost:8000/mcp"
    return FakeMCPClient()


class FakeMCPClient:
    """Fake async MCP client for generator tests."""

    async def __aenter__(self) -> FakeMCPClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def list_tools(self) -> list[object]:
        """Return fake MCP tool schemas."""
        return [
            SimpleNamespace(name="query_database", description="Run a SELECT query."),
            SimpleNamespace(name="list_tables", description="List tables."),
        ]
