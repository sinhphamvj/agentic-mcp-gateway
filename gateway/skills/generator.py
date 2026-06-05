# SPDX-License-Identifier: Apache-2.0
"""OpenClaw-compatible skill generator."""

from __future__ import annotations

from pathlib import Path

from gateway.mcp_client.http_client import MCPHttpClient


async def generate_skill_md(
    server_url: str,
    skill_name: str,
    skill_description: str,
    gateway_endpoint: str = "http://localhost:8001/generate",
    output_dir: str | Path | None = None,
) -> str:
    """Connect to an MCP server and generate an OpenClaw-compatible SKILL.md.

    Args:
        server_url: MCP Streamable HTTP endpoint.
        skill_name: Skill frontmatter name and output directory name.
        skill_description: Short skill frontmatter description.
        gateway_endpoint: Gateway endpoint OpenClaw should call.
        output_dir: Optional parent directory where ``skill_name/SKILL.md`` is written.

    Returns:
        Rendered SKILL.md content.
    """
    async with MCPHttpClient(server_url) as client:
        tools = await client.list_tools()

    content = _render_skill_md(
        skill_name=skill_name,
        skill_description=skill_description,
        gateway_endpoint=gateway_endpoint,
        tools=tools,
    )

    if output_dir is not None:
        skill_dir = Path(output_dir) / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    return content


def _render_skill_md(
    skill_name: str,
    skill_description: str,
    gateway_endpoint: str,
    tools: list[object],
) -> str:
    """Render SKILL.md content."""
    tool_descriptions = "\n".join(
        f"- **{_tool_attr(tool, 'name')}**: {_tool_attr(tool, 'description') or 'No description.'}"
        for tool in tools
    )
    if not tool_descriptions:
        tool_descriptions = "- No tools reported by the MCP server."

    return f"""---
name: {skill_name}
description: {skill_description}
---

# {skill_name}

## Available Capabilities
{tool_descriptions}

## How to Use
Replace <query> with the exact question from the user or agent.
Do not remove or modify any information from the original query.

```bash
curl -X POST {gateway_endpoint} \\
  -H "Content-Type: application/json" \\
  -d '{{"input_message": "<query>"}}'
```

## Important Rules
- Always pass the COMPLETE user question without modification
- Do not invent data; all information comes from the backend tools
- If the response contains an error, relay it to the user clearly
"""


def _tool_attr(tool: object, name: str) -> str:
    """Read a tool attribute from either an object or dict."""
    if isinstance(tool, dict):
        return str(tool.get(name, ""))
    return str(getattr(tool, name, ""))
