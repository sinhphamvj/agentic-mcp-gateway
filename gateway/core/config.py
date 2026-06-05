# SPDX-License-Identifier: Apache-2.0
"""Workflow configuration loading helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from gateway.core.models import WorkflowConfig

ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def load_config(path: str | Path) -> WorkflowConfig:
    """Load and validate a YAML workflow config.

    Args:
        path: File path to a workflow YAML document.

    Returns:
        Validated workflow configuration.

    Raises:
        FileNotFoundError: If the path does not exist.
        pydantic.ValidationError: If YAML content does not match the schema.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw = config_path.read_text(encoding="utf-8")
    substituted = ENV_VAR_PATTERN.sub(_replace_env_var, raw)
    data = yaml.safe_load(substituted) or {}
    return WorkflowConfig.model_validate(data)


def _replace_env_var(match: re.Match[str]) -> str:
    """Replace a regex match with the corresponding environment variable."""
    return os.environ.get(match.group(1), match.group(0))
