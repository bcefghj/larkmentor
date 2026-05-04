"""Unified observability layer — tracing, metrics, structured logging.

Integrates three concerns into a single importable module:

* **Tracing** — OpenTelemetry spans via ``@traced`` decorator and
  ``trace_tool_call`` context manager. Each Plan / Tool / MCP call gets its
  own span for end-to-end request stitching in Jaeger / Tempo.
* **Metrics** — Prometheus counters, histograms, and gauges exposed at
  ``/metrics``. Key signals: request counts, tool latency, LLM token usage,
  error rates, active plans.
* **Structured logs** — structlog with ``trace_id`` / ``plan_id`` / ``user_id``
  automatically injected into every log entry.

All external dependencies are **optional**. When a package is absent the
corresponding functionality degrades to silent no-ops so that tests, offline
demos, and minimal deployments keep running without modification.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Optional, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger("larkmentor.observability")

# ═══════════════════════════════════════════════════════════════════════════════
# Tracer setup (OpenTelemetry)
# ═══════════════════════════════════════════════════════════════════════════════

_tracer: Any = None
_otel_available = False

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )

    if os.getenv("LARKMENTOR_OTEL", "1") != "0":
        resource = Resource.create({"service.name": "larkmentor-agent-pilot"})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            if endpoint:
                provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
                )
        except Exception:
            pass
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("larkmentor")
        _otel_available = True
except Exception as exc:
    logger.debug("OpenTelemetry not available: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════════
# Prometheus metrics
# ═══════════════════════════════════════════════════════════════════════════════

_metrics: Dict[str, Any] = {}
_prom_available = False

try:
    from prometheus_client import Counter, Gauge, Histogram

    _metrics["pilot_requests_total"] = Counter(
        "pilot_requests_total",
        "Total requests received by Agent-Pilot",
        ["source", "status"],
    )
    _metrics["pilot_tool_duration_seconds"] = Histogram(
        "pilot_tool_duration_seconds",
        "Tool call duration in seconds",
        ["tool"],
        buckets=(0.01, 0.05, 0.1, 0.3, 0.5, 1, 2, 5, 10, 30, 60),
    )
    _metrics["pilot_llm_tokens_total"] = Counter(
        "pilot_llm_tokens_total",
        "Total LLM tokens consumed",
        ["provider", "model"],
    )
    _metrics["pilot_errors_total"] = Counter(
        "pilot_errors_total",
        "Total errors",
        ["error_type"],
    )
    _metrics["pilot_active_plans"] = Gauge(
        "pilot_active_plans",
        "Number of currently executing plans",
    )

    # Legacy metrics kept for backward compatibility
    _metrics["plan_started"] = Counter(
        "lm_plan_started_total", "Plans launched", ["source"],
    )
    _metrics["plan_completed"] = Counter(
        "lm_plan_completed_total", "Plans finished", ["status"],
    )
    _metrics["tool_latency"] = Histogram(
        "lm_tool_latency_seconds", "Tool call latency",
        ["tool"], buckets=(0.05, 0.1, 0.3, 0.5, 1, 2, 5, 10, 30, 60),
    )
    _metrics["tool_errors"] = Counter(
        "lm_tool_errors_total", "Tool failures", ["tool", "error_type"],
    )
    _metrics["llm_tokens"] = Counter(
        "lm_llm_tokens_total", "LLM token usage", ["model", "kind"],
    )
    _metrics["llm_cost_usd"] = Counter(
        "lm_llm_cost_usd_total", "LLM cost in USD", ["model"],
    )
    _metrics["ws_connections"] = Gauge(
        "lm_ws_connections", "Currently connected sync clients",
    )
    _metrics["hook_fires"] = Counter(
        "lm_hook_fires_total", "Lifecycle hook invocations", ["event"],
    )

    _prom_available = True
except Exception as exc:
    logger.debug("prometheus_client not available: %s", exc)


def incr(metric: str, value: float = 1, **labels: str) -> None:
    """Increment a Prometheus counter by *value*. No-op if metric absent."""
    m = _metrics.get(metric)
    if m is None:
        return
    try:
        if labels:
            m.labels(**labels).inc(value)
        else:
            m.inc(value)
    except Exception:
        pass


def observe(metric: str, value: float, **labels: str) -> None:
    """Record an observation on a Histogram. No-op if metric absent."""
    m = _metrics.get(metric)
    if m is None:
        return
    try:
        if labels:
            m.labels(**labels).observe(value)
        else:
            m.observe(value)
    except Exception:
        pass


def gauge_set(metric: str, value: float, **labels: str) -> None:
    """Set a Gauge to *value*. No-op if metric absent."""
    m = _metrics.get(metric)
    if m is None:
        return
    try:
        if labels:
            m.labels(**labels).set(value)
        else:
            m.set(value)
    except Exception:
        pass


# backward-compatible alias
gauge = gauge_set


# ═══════════════════════════════════════════════════════════════════════════════
# Tracing helpers
# ═══════════════════════════════════════════════════════════════════════════════


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[Any]:
    """Low-level span context manager. Yields the OTel span or None."""
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as sp:
        for k, v in attrs.items():
            try:
                sp.set_attribute(k, str(v))
            except Exception:
                pass
        yield sp


def trace_id() -> str:
    """Return the current OpenTelemetry trace ID as a hex string, or ``""``."""
    try:
        from opentelemetry import trace as _t
        ctx = _t.get_current_span().get_span_context()
        if ctx and ctx.trace_id:
            return f"{ctx.trace_id:032x}"
    except Exception:
        pass
    return ""


def traced(name: Optional[str] = None) -> Callable[[F], F]:
    """Decorator that wraps a function in an OpenTelemetry span.

    Usage::

        @traced()
        def my_function(x: int) -> int: ...

        @traced("custom-span-name")
        def another(): ...

    Span attributes automatically recorded: ``func``, ``duration_ms``,
    ``success``, ``error_type`` (on exception).
    """
    def decorator(fn: F) -> F:
        span_name = name or f"{fn.__module__}.{fn.__qualname__}"

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if _tracer is None:
                return fn(*args, **kwargs)
            with _tracer.start_as_current_span(span_name) as sp:
                sp.set_attribute("func", fn.__qualname__)
                t0 = time.perf_counter()
                try:
                    result = fn(*args, **kwargs)
                    sp.set_attribute("success", True)
                    return result
                except Exception as exc:
                    sp.set_attribute("success", False)
                    sp.set_attribute("error_type", type(exc).__name__)
                    sp.record_exception(exc)
                    raise
                finally:
                    sp.set_attribute("duration_ms", round((time.perf_counter() - t0) * 1000, 2))

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if _tracer is None:
                return await fn(*args, **kwargs)
            with _tracer.start_as_current_span(span_name) as sp:
                sp.set_attribute("func", fn.__qualname__)
                t0 = time.perf_counter()
                try:
                    result = await fn(*args, **kwargs)
                    sp.set_attribute("success", True)
                    return result
                except Exception as exc:
                    sp.set_attribute("success", False)
                    sp.set_attribute("error_type", type(exc).__name__)
                    sp.record_exception(exc)
                    raise
                finally:
                    sp.set_attribute("duration_ms", round((time.perf_counter() - t0) * 1000, 2))

        import asyncio
        if asyncio.iscoroutinefunction(fn):
            return async_wrapper  # type: ignore[return-value]
        return wrapper  # type: ignore[return-value]

    return decorator


@contextmanager
def trace_tool_call(tool_name: str, args: Optional[Dict[str, Any]] = None) -> Iterator[Any]:
    """Context manager that creates a span and records metrics for a tool call.

    Usage::

        with trace_tool_call("web_search", {"query": "hello"}) as sp:
            result = do_search()

    Automatically records:
    - Span attributes: tool name, sanitized args, duration, success/failure
    - Prometheus histogram observation for ``pilot_tool_duration_seconds``
    """
    t0 = time.perf_counter()
    success = True
    error_type = ""

    if _tracer is None:
        try:
            yield None
        except Exception as exc:
            success = False
            error_type = type(exc).__name__
            raise
        finally:
            duration = time.perf_counter() - t0
            observe("pilot_tool_duration_seconds", duration, tool=tool_name)
            if not success:
                incr("pilot_errors_total", error_type=error_type)
        return

    with _tracer.start_as_current_span(f"tool:{tool_name}") as sp:
        sp.set_attribute("tool.name", tool_name)
        if args:
            sp.set_attribute("tool.args", json.dumps(args, ensure_ascii=False, default=str)[:512])
        try:
            yield sp
        except Exception as exc:
            success = False
            error_type = type(exc).__name__
            sp.set_attribute("success", False)
            sp.set_attribute("error_type", error_type)
            sp.record_exception(exc)
            raise
        else:
            sp.set_attribute("success", True)
        finally:
            duration = time.perf_counter() - t0
            sp.set_attribute("duration_ms", round(duration * 1000, 2))
            observe("pilot_tool_duration_seconds", duration, tool=tool_name)
            if not success:
                incr("pilot_errors_total", error_type=error_type)


# ═══════════════════════════════════════════════════════════════════════════════
# Structured logging (structlog)
# ═══════════════════════════════════════════════════════════════════════════════

_slog: Any = None

try:
    import structlog

    def _inject_trace(_logger: Any, _method: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
        tid = trace_id()
        if tid:
            event_dict.setdefault("trace_id", tid)
        return event_dict

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_trace,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if os.getenv("LARKMENTOR_LOG_DEV") else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, os.getenv("LARKMENTOR_LOG_LEVEL", "INFO").upper(), logging.INFO)
        ),
        context_class=dict,
    )
    _slog = structlog.get_logger("larkmentor")
except Exception as exc:
    logger.debug("structlog not available: %s", exc)


def slog() -> Any:
    """Return the structured logger (or stdlib logger if structlog is absent)."""
    return _slog or logger


# ═══════════════════════════════════════════════════════════════════════════════
# Audit JSONL writer
# ═══════════════════════════════════════════════════════════════════════════════

_AUDIT_PATH = os.path.expanduser(
    os.getenv("LARKMENTOR_AUDIT_LOG", os.path.join("~", ".larkmentor", "audit.jsonl"))
)


def audit(event_type: str, **kwargs: Any) -> None:
    """Append-only JSONL audit writer. Thread-safe, never raises.

    Parameters
    ----------
    event_type:
        A short, machine-readable event classifier (e.g. ``"tool_call"``).
    **kwargs:
        Arbitrary fields persisted alongside the event.
    """
    try:
        os.makedirs(os.path.dirname(_AUDIT_PATH), exist_ok=True)
        rec: Dict[str, Any] = {
            "ts": int(time.time()),
            "event": event_type,
            "trace_id": trace_id(),
            **kwargs,
        }
        with open(_AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI integration
# ═══════════════════════════════════════════════════════════════════════════════


def install_fastapi(app: Any) -> None:
    """Wire up Prometheus ``/metrics`` endpoint and OpenTelemetry FastAPI instrumentation.

    Safe to call even if prometheus_client / opentelemetry are not installed —
    each integration is attempted independently with graceful fallback.
    """
    if _prom_available:
        try:
            from prometheus_client import make_asgi_app
            app.mount("/metrics", make_asgi_app())
            logger.info("prometheus /metrics mounted")
        except Exception as exc:
            logger.debug("prometheus mount skipped: %s", exc)

    if _otel_available:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
            logger.info("OpenTelemetry FastAPI instrumented")
        except Exception as exc:
            logger.debug("otel fastapi instrument skipped: %s", exc)


# backward-compatible alias
setup_metrics_endpoint = install_fastapi


__all__ = [
    "audit",
    "gauge",
    "gauge_set",
    "incr",
    "install_fastapi",
    "observe",
    "setup_metrics_endpoint",
    "slog",
    "span",
    "trace_id",
    "trace_tool_call",
    "traced",
]
