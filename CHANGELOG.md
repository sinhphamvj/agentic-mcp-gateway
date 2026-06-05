# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-05

### Added
- Initial release of agentic-mcp-gateway framework.
- Core LangGraph-powered intent routing and orchestration engine.
- Multi-LLM provider support including OpenAI, Anthropic, NVIDIA NIM, and Ollama.
- YAML-first configuration system for workflows and agent definitions.
- OpenClaw-compatible skill export functionality (`amcpg skills openclaw-setup`).
- Native OpenTelemetry (OTel) observability and Arize Phoenix integration.
- Starlette and Uvicorn based HTTP transport for MCP server communication.
- Comprehensive CLI for gateway management (`amcpg`).
- 3 Fully functional demo examples (music-store, devops-assistant, research-agent).
- Complete CI/CD GitHub workflows, templates, and comprehensive documentation.
