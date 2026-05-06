"""OpenTelemetry tracing — 可选启用.

设置 OTEL_ENABLED=1 + OTEL_EXPORTER_OTLP_ENDPOINT 后启用。
默认 NoOp 不影响性能。
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("pilot.governance.otel")


_ENABLED = os.getenv("OTEL_ENABLED", "0") == "1"
_tracer: Any = None


def _init_tracer():
    global _tracer
    if _tracer is not None:
        return _tracer
    if not _ENABLED:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "agent-pilot-v1"})
        provider = TracerProvider(resource=resource)

        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            ep = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
            if ep:
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=ep)))
        except Exception:
            pass

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("pilot")
        return _tracer
    except ImportError:
        logger.debug("OpenTelemetry SDK not installed")
        return None


@contextmanager
def span(name: str, **attrs) -> Iterator[Any]:
    """统一 span 上下文管理器."""
    tracer = _init_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name) as s:
        for k, v in attrs.items():
            try:
                s.set_attribute(k, v)
            except Exception:
                pass
        yield s
