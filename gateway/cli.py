# SPDX-License-Identifier: Apache-2.0
"""Command-line interface for the agentic MCP gateway."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from gateway.core.config import load_config
from gateway.skills.generator import generate_skill_md


@click.group()
@click.version_option()
def main() -> None:
    """Run and manage agentic MCP gateway workflows."""


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind.")
@click.option("--port", default=8001, show_default=True, help="Port to bind.")
def serve(host: str, port: int) -> None:
    """Start the gateway HTTP server."""
    click.echo(f"Serving agentic-mcp-gateway on {host}:{port}")


@main.group()
def skills() -> None:
    """Manage OpenClaw-compatible skill exports."""


@skills.command("export")
@click.option("--output", default="skills", show_default=True, help="Output directory.")
def export_skills(output: str) -> None:
    """Export MCP tool schemas as agent skills."""
    click.echo(f"Skill export placeholder: {output}")


@skills.command("generate")
@click.option("--server-url", required=True, help="MCP server Streamable HTTP endpoint.")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Output directory.",
)
@click.option("--name", "skill_name", required=True, help="Generated skill name.")
@click.option("--desc", "skill_description", required=True, help="Generated skill description.")
@click.option(
    "--gateway-endpoint",
    default="http://localhost:8001/generate",
    show_default=True,
    help="Gateway HTTP endpoint used in SKILL.md.",
)
def generate_skill(
    server_url: str,
    output_dir: Path,
    skill_name: str,
    skill_description: str,
    gateway_endpoint: str,
) -> None:
    """Generate one OpenClaw-compatible SKILL.md from an MCP server."""
    asyncio.run(
        generate_skill_md(
            server_url=server_url,
            skill_name=skill_name,
            skill_description=skill_description,
            gateway_endpoint=gateway_endpoint,
            output_dir=output_dir,
        )
    )
    click.echo(f"Wrote {output_dir / skill_name / 'SKILL.md'}")


@skills.command("openclaw-setup")
@click.option("--config", "config_path", type=click.Path(path_type=Path), required=True)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("openclaw"),
    show_default=True,
    help="Directory where SOUL.md and generated skills are written.",
)
def openclaw_setup(config_path: Path, output_dir: Path) -> None:
    """Generate SOUL.md and SKILL.md files for a workflow config."""
    config = load_config(config_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    gateway_endpoint = f"http://localhost:{config.gateway_port}/generate"
    generated_skills: list[str] = []

    for server in config.mcp_servers:
        if server.transport != "http" or not server.url:
            raise click.ClickException(
                f"OpenClaw setup requires an HTTP URL for MCP server '{server.name}'."
            )
        asyncio.run(
            generate_skill_md(
                server_url=server.url,
                skill_name=server.name,
                skill_description=server.description or f"Use MCP server {server.name}.",
                gateway_endpoint=gateway_endpoint,
                output_dir=output_dir,
            )
        )
        generated_skills.append(server.name)

    soul_path = output_dir / "SOUL.md"
    soul_path.write_text(_render_soul_md(generated_skills, gateway_endpoint), encoding="utf-8")
    click.echo(f"Wrote {soul_path}")
    for skill_name in generated_skills:
        click.echo(f"Wrote {output_dir / skill_name / 'SKILL.md'}")


def _render_soul_md(skill_names: list[str], gateway_endpoint: str) -> str:
    """Render a minimal OpenClaw SOUL.md file for the generated skills."""
    skill_lines = "\n".join(f"- {skill_name}" for skill_name in skill_names)
    return f"""# agentic-mcp-gateway Agent

Use the generated OpenClaw skills to route user requests through agentic-mcp-gateway.

Gateway endpoint: `{gateway_endpoint}`

## Skills
{skill_lines}

## Operating Rules
- Preserve the complete user request when invoking generated skills.
- Report backend errors clearly.
- Do not invent data that was not returned by the gateway.
"""


if __name__ == "__main__":
    main()
