"""Unified observability layer (P5.1 + P5.2).

Pulls together three concerns that used to be scattered:

* **Tracing** — OpenTelemetry. We create a Tracer named ``larkmentor`` and
  wire FastAPI's instrumentor when available. Each Plan / Tool / MCP call
  gets its own span so a single request can be stitched from IM → Agent →
  Tool in Jaeger.
* **Metrics** — Prometheus counters and histograms. ``/metrics`` is
  served by the dashboard when prometheus_client is installed.
* **Structured logs** — structlog with ``trace_id`` + ``plan_id`` + ``user_id``
  automatically attached.

All dependencies are *optional*. If a package is missing the module
degrades to no-ops so tests / offline demos keep running.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger("larkmentor.observability")

# ── Tracer setup ────────────────────────────────────────────────────────────

_tracer: Any = None
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
except Exception as e:
    logger.debug("OpenTelemetry not available: %s", e)


# ── Prometheus ──────────────────────────────────────────────────────────────

_metrics: Dict[str, Any] = {}
try:
    from prometheus_client import Counter, Histogram, Gauge

    _metrics["plan_started"] = Counter(
        "lm_plan_started_total",
        "Plans launched",
        ["source"],
    )
    _metrics["plan_completed"] = Counter(
        "lm_plan_completed_total",
        "Plans finished",
        ["status"],
    )
    _metrics["tool_latency"] = Histogram(
        "lm_tool_latency_seconds",
        "Tool call latency",
        ["tool"],
        buckets=(0.05, 0.1, 0.3, 0.5, 1, 2, 5, 10, 30, 60),
    )
    _metrics["tool_errors"] = Counter(
        "lm_tool_errors_total",
        "Tool failures",
        ["tool", "error_type"],
    )
    _metrics["llm_tokens"] = Counter(
        "lm_llm_tokens_total",
        "LLM token usage",
        ["model", "kind"],
    )
    _metrics["llm_cost_usd"] = Counter(
        "lm_llm_cost_usd_total",
        "LLM cost in USD",
        ["model"],
    )
    _metrics["ws_connections"] = Gauge(
        "lm_ws_connections",
        "Currently connected sync clients",
    )
    _metrics["hook_fires"] = Counter(
        "lm_hook_fires_total",
        "Lifecycle hook invocations",
        ["event"],
    )
except Exception as e:
    logger.debug("prometheus_client not available: %s", e)


def incr(metric: str, value: float = 1, **labels: str) -> None:
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


def gauge(metric: str, value: float, **labels: str) -> None:
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


# ── Tracing helper ──────────────────────────────────────────────────────────


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[Any]:
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
    try:
        from opentelemetry import trace as _t
        ctx = _t.get_current_span().get_span_context()
        if ctx and ctx.trace_id:
            return f"{ctx.trace_id:032x}"
    except Exception:
        pass
    return ""


# ── structlog ────────────────────────────────────────────────────────────────

_structlog: Any = None
try:
    import structlog

    def _inject_trace(_, __, event_dict):
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
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
    )
    _structlog = structlog.get_logger("larkmentor")
except Exception as e:
    logger.debug("structlog not available: %s", e)


def slog() -> Any:
    """Return the structured logger (or std logger if structlog absent)."""
    return _structlog or logger


# ── Audit JSONL writer (P5.2) ────────────────────────────────────────────────


_AUDIT_PATH = os.path.expanduser(
    os.getenv("LARKMENTOR_AUDIT_LOG",
              os.path.join("~", ".larkmentor", "audit.jsonl"))
)


def audit(event: str, **fields: Any) -> None:
    """Append-only JSONL audit writer. Safe to call from any thread."""
    import json
    try:
        os.makedirs(os.path.dirname(_AUDIT_PATH), exist_ok=True)
        rec = {
            "ts": int(time.time()),
            "event": event,
            "trace_id": trace_id(),
            **fields,
        }
        with open(_AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def install_fastapi(app: Any) -> None:
    """Wire up Prometheus /metrics and OpenTelemetry FastAPI instrumentation."""
    try:
        from prometheus_client import make_asgi_app
        app.mount("/metrics", make_asgi_app())
        logger.info("prometheus /metrics mounted")
    except Exception as e:
        logger.debug("prometheus mount skipped: %s", e)
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry FastAPI instrumented")
    except Exception as e:
        logger.debug("otel fastapi instrument skipped: %s", e)
