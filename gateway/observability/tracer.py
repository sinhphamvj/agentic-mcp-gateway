# SPDX-License-Identifier: Apache-2.0
"""OpenTelemetry tracing helpers for the agentic-mcp-gateway.

Provides singleton tracer setup, contextmanager-based span helpers for
MCP tool calls, LLM chat completions, and intent routing decisions.
All trace functions respect the ``enable_tracing`` configuration flag —
when tracing is disabled they return no-op context managers.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_tracer: trace.Tracer | None = None
_tracing_enabled: bool = True


def setup_tracing(
    service_name: str = "agentic-mcp-gateway",
    *,
    enabled: bool = True,
) -> trace.Tracer:
    """Initialize OpenTelemetry with an OTLP/gRPC exporter.

    If ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set in the environment it is
    used as the collector endpoint; otherwise the exporter targets
    ``http://localhost:4317`` (the default OTLP/gRPC port, which Phoenix
    proxies when started with ``PHOENIX_GRPC_PORT``).

    Args:
        service_name: The ``service.name`` resource attribute.
        enabled: When *False* the global tracer is a no-op tracer.

    Returns:
        A configured ``Tracer`` instance.
    """
    global _tracer, _tracing_enabled  # noqa: PLW0603
    _tracing_enabled = enabled

    if not enabled:
        _tracer = trace.get_tracer(service_name)
        return _tracer

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    endpoint = os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://localhost:4317",
    )
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _tracer = trace.get_tracer(service_name)
    return _tracer


def get_tracer() -> trace.Tracer:
    """Return the singleton tracer, initialising lazily if needed."""
    global _tracer  # noqa: PLW0603
    if _tracer is None:
        _tracer = setup_tracing()
    return _tracer


def is_tracing_enabled() -> bool:
    """Return *True* if tracing was set up in enabled mode."""
    return _tracing_enabled


# ---------------------------------------------------------------------------
# Span context-managers
# ---------------------------------------------------------------------------


@contextmanager
def trace_tool_call(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> Generator[trace.Span | None, None, None]:
    """Trace an MCP tool invocation.

    Yields the active ``Span`` (or *None* if tracing is disabled).
    The span is ended automatically when the context exits.

    Attributes set on the span:
        ``mcp.server``, ``mcp.tool``, ``mcp.arguments``
    """
    if not _tracing_enabled:
        yield None
        return

    tracer = get_tracer()
    with tracer.start_as_current_span(f"mcp.tool.{tool_name}") as span:
        span.set_attribute("mcp.server", server_name)
        span.set_attribute("mcp.tool", tool_name)
        span.set_attribute("mcp.arguments", str(arguments))
        yield span


@contextmanager
def trace_llm_call(
    provider: str,
    model: str,
    token_count: int = 0,
) -> Generator[trace.Span | None, None, None]:
    """Trace an LLM chat-completion call.

    Attributes set on the span:
        ``llm.provider``, ``llm.model``, ``llm.tokens``
    """
    if not _tracing_enabled:
        yield None
        return

    tracer = get_tracer()
    with tracer.start_as_current_span(f"llm.chat.{provider}") as span:
        span.set_attribute("llm.provider", provider)
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.tokens", token_count)
        yield span


@contextmanager
def trace_router_decision(
    intent: str,
    confidence: float,
) -> Generator[trace.Span | None, None, None]:
    """Trace an intent-routing decision.

    Attributes set on the span:
        ``router.intent``, ``router.confidence``
    """
    if not _tracing_enabled:
        yield None
        return

    tracer = get_tracer()
    with tracer.start_as_current_span("router.classify") as span:
        span.set_attribute("router.intent", intent)
        span.set_attribute("router.confidence", confidence)
        yield span
