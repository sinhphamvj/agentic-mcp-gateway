# Contributing to agentic-mcp-gateway

Welcome to the `agentic-mcp-gateway` project! We appreciate your interest in contributing. This guide outlines the steps and rules for contributing to the repository.

## Setup Instructions

This project uses [`uv`](https://github.com/astral-sh/uv) for fast Python package management.

1. Ensure you have Python 3.12+ installed on your system.
2. Install `uv` if you haven't already.
3. Clone the repository and install the development dependencies:
   ```bash
   git clone https://github.com/your-org/agentic-mcp-gateway.git
   cd agentic-mcp-gateway
   uv sync --dev
   ```

## Code Style

We enforce strict code style and typing requirements to maintain high code quality:
- **Formatting & Linting:** We use `ruff`.
- **Type Checking:** We use `mypy`. All functions must have type hints.
- **Docstrings:** Use Google-style docstrings. Every module MUST have a module-level docstring.
- **Line length:** Maximum 100 characters. Indentation: 4 spaces.
- **License Headers:** Every source file MUST contain an Apache-2.0 license header at the top.
- **Imports:** Sorted with `ruff isort`.
- **Async:** Use `async/await` for ALL I/O. Use Pydantic BaseModel for configs.

## Testing Rules

We use `pytest` and `pytest-asyncio` for testing.
- **Coverage:** We maintain a strict test coverage target of **> 80%**.
- Write tests for your changes in `tests/test_<module>.py`.
- Run the test suite and check coverage using:
  ```bash
  uv run pytest --cov=gateway --cov=servers
  ```
- **Mocking:** Mock LLM calls in unit tests; use real calls only in integration tests.
- All MCP servers must have integration tests and use pytest fixtures for client/server setup.

## Pull Request Process

1. Fork the repository and create your branch from `main`.
2. Ensure all tests pass: `uv run pytest --cov=gateway --cov=servers`
3. Ensure code is formatted: `uv run ruff format .`
4. Ensure linting passes: `uv run ruff check .`
5. Ensure type checks pass: `uv run mypy .`
6. Submit your PR with a clear description of the changes and the rationale behind them.
