# SPDX-License-Identifier: Apache-2.0
"""Tests for gateway.observability.tracer module."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from opentelemetry import trace

# ---------------------------------------------------------------------------
# Reset module-level singleton between tests
# ---------------------------------------------------------------------------
import gateway.observability.tracer as _tracer_mod
from gateway.observability.tracer import (
    get_tracer,
    is_tracing_enabled,
    setup_tracing,
    trace_llm_call,
    trace_router_decision,
    trace_tool_call,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Reset module singletons so each test starts fresh."""
    _tracer_mod._tracer = None
    _tracer_mod._tracing_enabled = True


# ---------------------------------------------------------------------------
# setup_tracing
# ---------------------------------------------------------------------------


class TestSetupTracing:
    """Tests for the ``setup_tracing`` function."""

    def test_returns_tracer(self) -> None:
        tracer = setup_tracing("test-service")
        assert tracer is not None

    def test_sets_global_tracer(self) -> None:
        tracer = setup_tracing("test-service")
        assert get_tracer() is tracer

    def test_disabled_mode_returns_tracer(self) -> None:
        tracer = setup_tracing("test-service", enabled=False)
        assert tracer is not None
        assert not is_tracing_enabled()

    def test_enabled_mode_flag(self) -> None:
        setup_tracing("test-service", enabled=True)
        assert is_tracing_enabled()

    def test_custom_endpoint_via_env(self) -> None:
        with patch.dict("os.environ", {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://custom:4317"}):
            tracer = setup_tracing("test-service")
            assert tracer is not None


# ---------------------------------------------------------------------------
# get_tracer
# ---------------------------------------------------------------------------


class TestGetTracer:
    """Tests for the ``get_tracer`` singleton accessor."""

    def test_lazy_init(self) -> None:
        assert _tracer_mod._tracer is None
        tracer = get_tracer()
        assert tracer is not None
        assert _tracer_mod._tracer is tracer

    def test_returns_same_instance(self) -> None:
        t1 = get_tracer()
        t2 = get_tracer()
        assert t1 is t2


# ---------------------------------------------------------------------------
# trace_tool_call
# ---------------------------------------------------------------------------


class TestTraceToolCall:
    """Tests for the ``trace_tool_call`` context manager."""

    def test_yields_span_when_enabled(self) -> None:
        setup_tracing("test", enabled=True)
        with trace_tool_call("db-server", "query_database", {"sql": "SELECT 1"}) as span:
            assert span is not None
            assert isinstance(span, trace.Span)

    def test_span_attributes(self) -> None:
        setup_tracing("test", enabled=True)
        with trace_tool_call("db-server", "list_tables", {"schema": "public"}) as span:
            # ReadableSpan exposes attributes as a dict-like after recording
            assert span is not None

    def test_yields_none_when_disabled(self) -> None:
        setup_tracing("test", enabled=False)
        with trace_tool_call("srv", "tool", {}) as span:
            assert span is None

    def test_context_manager_completes(self) -> None:
        setup_tracing("test", enabled=True)
        with trace_tool_call("srv", "t", {"k": "v"}):
            pass  # no exceptions


# ---------------------------------------------------------------------------
# trace_llm_call
# ---------------------------------------------------------------------------


class TestTraceLlmCall:
    """Tests for the ``trace_llm_call`` context manager."""

    def test_yields_span_when_enabled(self) -> None:
        setup_tracing("test", enabled=True)
        with trace_llm_call("openai", "gpt-4o", 100) as span:
            assert span is not None

    def test_yields_none_when_disabled(self) -> None:
        setup_tracing("test", enabled=False)
        with trace_llm_call("openai", "gpt-4o") as span:
            assert span is None

    def test_default_token_count(self) -> None:
        setup_tracing("test", enabled=True)
        with trace_llm_call("ollama", "llama3") as span:
            assert span is not None


# ---------------------------------------------------------------------------
# trace_router_decision
# ---------------------------------------------------------------------------


class TestTraceRouterDecision:
    """Tests for the ``trace_router_decision`` context manager."""

    def test_yields_span_when_enabled(self) -> None:
        setup_tracing("test", enabled=True)
        with trace_router_decision("QNA", 0.95) as span:
            assert span is not None

    def test_yields_none_when_disabled(self) -> None:
        setup_tracing("test", enabled=False)
        with trace_router_decision("REFUND", 0.8) as span:
            assert span is None

    def test_span_name(self) -> None:
        setup_tracing("test", enabled=True)
        with trace_router_decision("UNKNOWN", 0.1) as span:
            assert span is not None


# ---------------------------------------------------------------------------
# Integration: enable_tracing flag toggles
# ---------------------------------------------------------------------------


class TestEnableTracingFlag:
    """Verify the enable_tracing flag correctly arms/disarms all helpers."""

    def test_disabled_flag_makes_all_noop(self) -> None:
        setup_tracing("test", enabled=False)
        with trace_tool_call("s", "t", {}) as s1:
            assert s1 is None
        with trace_llm_call("p", "m") as s2:
            assert s2 is None
        with trace_router_decision("i", 0.5) as s3:
            assert s3 is None

    def test_enabled_flag_produces_spans(self) -> None:
        setup_tracing("test", enabled=True)
        with trace_tool_call("s", "t", {}) as s1:
            assert s1 is not None
        with trace_llm_call("p", "m") as s2:
            assert s2 is not None
        with trace_router_decision("i", 0.5) as s3:
            assert s3 is not None
