"""Agent-Pilot structured logging with JSON support.

Provides both human-readable (dev) and JSON (production) log formats.
Toggle via AGENT_PILOT_LOG_FORMAT env var: "json" or "text" (default).
"""

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from typing import Optional

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")


def set_request_context(*, request_id: str = "", trace_id: str = "", user_id: str = "") -> None:
    if request_id:
        _request_id.set(request_id)
    if trace_id:
        _trace_id.set(trace_id)
    if user_id:
        _user_id.set(user_id)


def new_request_id() -> str:
    rid = f"req_{uuid.uuid4().hex[:12]}"
    _request_id.set(rid)
    return rid


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production use."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        rid = _request_id.get("")
        if rid:
            log_entry["request_id"] = rid
        tid = _trace_id.get("")
        if tid:
            log_entry["trace_id"] = tid
        uid = _user_id.get("")
        if uid:
            log_entry["user_id"] = uid
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        for key in ("duration_ms", "tool", "plan_id", "step_id", "status"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val
        return json.dumps(log_entry, ensure_ascii=False, default=str)


class DevFormatter(logging.Formatter):
    """Human-readable colored formatter for development."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        rid = _request_id.get("")
        rid_str = f" [{rid}]" if rid else ""
        prefix = f"{color}{record.levelname:>7}{self.RESET}"
        ts = self.formatTime(record, datefmt="%H:%M:%S")
        return f"{ts} {prefix} [{record.name}]{rid_str} {record.getMessage()}"


def configure_logging(*, level: str = "INFO", format_type: Optional[str] = None) -> None:
    """Configure application-wide logging."""
    if format_type is None:
        format_type = os.getenv("AGENT_PILOT_LOG_FORMAT", "text")

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    if format_type == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(DevFormatter())

    root.addHandler(handler)

    for name in ("urllib3", "httpcore", "httpx", "openai", "websockets"):
        logging.getLogger(name).setLevel(logging.WARNING)
