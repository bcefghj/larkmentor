"""Resilience utilities: retry, circuit breaker, timeout, error reporting.

Provides production-grade fault tolerance patterns used across the project.
"""

from __future__ import annotations

import functools
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger("pilot.resilience")

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay_sec: float = 1.0
    max_delay_sec: float = 30.0
    jitter: bool = True
    retryable_exceptions: tuple = (Exception,)


def retry_with_backoff(config: Optional[RetryConfig] = None):
    """Decorator: retry a function with exponential backoff + jitter."""
    cfg = config or RetryConfig()

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(cfg.max_attempts):
                try:
                    return fn(*args, **kwargs)
                except cfg.retryable_exceptions as e:
                    last_exc = e
                    if attempt == cfg.max_attempts - 1:
                        break
                    delay = min(cfg.base_delay_sec * (2**attempt), cfg.max_delay_sec)
                    if cfg.jitter:
                        delay *= 0.5 + random.random()
                    logger.warning(
                        "retry %s attempt=%d/%d delay=%.1fs err=%s",
                        fn.__name__,
                        attempt + 1,
                        cfg.max_attempts,
                        delay,
                        e,
                    )
                    time.sleep(delay)
            raise last_exc  # type: ignore

        return wrapper  # type: ignore

    return decorator


@dataclass
class CircuitBreakerState:
    failure_count: int = 0
    last_failure_ts: float = 0.0
    state: str = "closed"  # closed / open / half_open
    success_count_half_open: int = 0


class CircuitBreaker:
    """Simple circuit breaker: opens after N consecutive failures,
    allows a single probe after cooldown, then resets on success."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout_sec: float = 60.0):
        self._threshold = failure_threshold
        self._recovery_sec = recovery_timeout_sec
        self._state = CircuitBreakerState()
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._state.state == "open":
                if time.time() - self._state.last_failure_ts > self._recovery_sec:
                    self._state.state = "half_open"
                    return False
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._state.failure_count = 0
            self._state.state = "closed"

    def record_failure(self) -> None:
        with self._lock:
            self._state.failure_count += 1
            self._state.last_failure_ts = time.time()
            if self._state.failure_count >= self._threshold:
                self._state.state = "open"
                logger.error(
                    "circuit breaker OPEN after %d failures",
                    self._state.failure_count,
                )


class TimeoutError(Exception):
    """Raised when a tool execution exceeds the configured timeout."""


def run_with_timeout(fn: Callable, timeout_sec: float = 30.0, **kwargs) -> Any:
    """Run a callable with a timeout. Raises TimeoutError if exceeded."""
    result = [None]
    exception = [None]

    def _target():
        try:
            result[0] = fn(**kwargs)
        except Exception as e:
            exception[0] = e

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)

    if t.is_alive():
        raise TimeoutError(f"{fn.__name__} exceeded {timeout_sec}s timeout")
    if exception[0] is not None:
        raise exception[0]
    return result[0]


class WebSocketReconnector:
    """Manages WebSocket reconnection with exponential backoff.

    Usage:
        reconnector = WebSocketReconnector(connect_fn=my_connect)
        reconnector.start()  # runs in background, auto-reconnects on failure
    """

    def __init__(
        self,
        connect_fn: Callable,
        *,
        max_delay_sec: float = 60.0,
        base_delay_sec: float = 1.0,
        on_connected: Optional[Callable] = None,
        on_disconnected: Optional[Callable] = None,
    ):
        self._connect_fn = connect_fn
        self._max_delay = max_delay_sec
        self._base_delay = base_delay_sec
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._attempt = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                self._connect_fn()
                self._attempt = 0
                if self._on_connected:
                    self._on_connected()
            except Exception as e:
                self._attempt += 1
                if self._on_disconnected:
                    self._on_disconnected(e)
                delay = min(self._base_delay * (2**self._attempt), self._max_delay)
                delay *= 0.5 + random.random()
                logger.warning(
                    "WebSocket reconnect attempt=%d delay=%.1fs err=%s",
                    self._attempt,
                    delay,
                    e,
                )
                time.sleep(delay)


def notify_user_error(
    user_open_id: str,
    error: Exception,
    *,
    context: str = "",
    severity: str = "warning",
) -> None:
    """Send an error notification to the user via Feishu card.

    This is the unified way to report errors to users instead of
    silently swallowing exceptions.
    """
    try:
        from bot.message_sender import send_text

        error_msg = f"⚠️ Agent-Pilot 执行异常\n\n错误类型: {type(error).__name__}\n详情: {str(error)[:200]}\n"
        if context:
            error_msg += f"上下文: {context}\n"
        error_msg += "\n请稍后重试，或输入 /pilot 重新启动任务。"
        send_text(user_open_id, error_msg)
    except Exception as notify_err:
        logger.error(
            "failed to notify user %s about error: %s (original: %s)",
            user_open_id,
            notify_err,
            error,
        )
