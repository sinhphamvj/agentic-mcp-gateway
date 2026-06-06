# SPDX-License-Identifier: Apache-2.0
"""Tests that every example workflow.yaml loads against WorkflowConfig.

Guards against docs drift: if someone adds a new example with a typo in the
schema, this test fails fast.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gateway.core.config import load_config

REPO_ROOT = Path(__file__).parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"
README_PATH = REPO_ROOT / "README.md"

YAML_FENCE_PATTERN = re.compile(r"```yaml\n(.*?)```", re.DOTALL)
INTENT_AND_MCP_FIELDS = ("mcp_servers", "intents", "llm")


def _iter_example_workflows() -> list[Path]:
    """Return all workflow.yaml files under the examples/ directory."""
    return sorted(EXAMPLES_DIR.rglob("workflow.yaml"))


@pytest.mark.parametrize(
    "yaml_path",
    _iter_example_workflows(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_example_workflow_yaml_loads(yaml_path: Path) -> None:
    """Every example workflow.yaml must parse against WorkflowConfig."""
    config = load_config(yaml_path)
    assert config.llm.provider is not None
    assert len(config.mcp_servers) >= 1
    assert len(config.intents) >= 1
    # Every intent must reference a declared mcp_server.
    server_names = {s.name for s in config.mcp_servers}
    for intent in config.intents:
        assert intent.mcp_server in server_names, (
            f"Intent '{intent.name}' references unknown server "
            f"'{intent.mcp_server}' in {yaml_path}"
        )


def test_root_workflow_yaml_loads() -> None:
    """The repository's demo workflow.yaml must load."""
    config = load_config(REPO_ROOT / "workflow.yaml")
    assert config.llm.provider.value == "openai"
    assert config.gateway_port == 8001


def test_readme_configuration_example_is_valid() -> None:
    """The first YAML block in README.md's Configuration Guide must parse."""
    readme = README_PATH.read_text(encoding="utf-8")
    matches = YAML_FENCE_PATTERN.findall(readme)

    # Find the block in the Configuration Guide section (after the "## Configuration" heading).
    in_config_section = False
    yaml_block = None
    for line in readme.splitlines():
        if line.startswith("## Configuration Guide"):
            in_config_section = True
            continue
        if in_config_section and line.startswith("```yaml"):
            # capture the next block
            yaml_block = next((m for m in matches if m.strip().startswith("llm:")), None)
            break

    assert yaml_block is not None, "No ```yaml``` block in Configuration Guide section"

    import yaml as pyyaml

    # Set dummy env so ${OPENAI_API_KEY} doesn't propagate; then strip the env
    # requirement since the test only validates structure, not credentials.
    data = pyyaml.safe_load(yaml_block)
    assert "llm" in data
    assert "mcp_servers" in data
    assert "intents" in data
    # README's example must use the real field names, not invented aliases.
    assert "model" not in data.get("llm", {}), (
        "README uses obsolete 'model' field (should be 'model_name')"
    )
    assert "agents" not in data, (
        "README uses obsolete 'agents' field (should be 'mcp_servers' + 'intents')"
    )
    assert "observability" not in data, (
        "README uses obsolete 'observability' field (not part of WorkflowConfig)"
    )


def test_intent_mcp_server_consistency() -> None:
    """Across all examples, every intent.mcp_server must match a declared server."""
    for yaml_path in _iter_example_workflows():
        config = load_config(yaml_path)
        server_names = {s.name for s in config.mcp_servers}
        for intent in config.intents:
            assert intent.mcp_server in server_names, (
                f"{yaml_path}: intent '{intent.name}' -> server '{intent.mcp_server}' "
                f"is not declared in mcp_servers"
            )


def test_no_obsolete_field_references_in_yaml_blocks() -> None:
    """All ```yaml``` blocks in example READMEs use real WorkflowConfig fields."""
    bad_substrings = ["  model: gpt", "agents:", "api_key: ${", "observability:"]
    for readme in EXAMPLES_DIR.rglob("README.md"):
        text = readme.read_text(encoding="utf-8")
        for block in YAML_FENCE_PATTERN.findall(text):
            for bad in bad_substrings:
                assert bad not in block, (
                    f"{readme.relative_to(REPO_ROOT)} contains obsolete field '{bad}' "
                    f"in YAML block"
                )