"""Tests for core/resilience.py — retry, circuit breaker, timeout."""

import threading
import time

import pytest


def test_retry_with_backoff_succeeds_after_retries():
    from core.resilience import retry_with_backoff, RetryConfig

    call_count = [0]

    @retry_with_backoff(RetryConfig(max_attempts=3, base_delay_sec=0.01))
    def flaky():
        call_count[0] += 1
        if call_count[0] < 3:
            raise ValueError("not yet")
        return "ok"

    assert flaky() == "ok"
    assert call_count[0] == 3


def test_retry_with_backoff_raises_after_max_attempts():
    from core.resilience import retry_with_backoff, RetryConfig

    @retry_with_backoff(RetryConfig(max_attempts=2, base_delay_sec=0.01))
    def always_fails():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        always_fails()


def test_circuit_breaker_opens_and_recovers():
    from core.resilience import CircuitBreaker

    cb = CircuitBreaker(failure_threshold=3, recovery_timeout_sec=0.1)
    assert not cb.is_open

    for _ in range(3):
        cb.record_failure()
    assert cb.is_open

    time.sleep(0.15)
    assert not cb.is_open  # half_open after recovery timeout

    cb.record_success()
    assert not cb.is_open


def test_run_with_timeout_succeeds():
    from core.resilience import run_with_timeout

    result = run_with_timeout(lambda: 42, timeout_sec=1.0)
    assert result == 42


def test_run_with_timeout_raises_on_slow_fn():
    from core.resilience import run_with_timeout, TimeoutError

    def slow():
        time.sleep(5)
        return "never"

    with pytest.raises(TimeoutError):
        run_with_timeout(slow, timeout_sec=0.1)


def test_websocket_reconnector_retries():
    from core.resilience import WebSocketReconnector

    attempts = [0]
    connected = [False]

    def connect():
        attempts[0] += 1
        if attempts[0] < 3:
            raise ConnectionError("refused")
        connected[0] = True
        raise KeyboardInterrupt  # stop loop

    reconnector = WebSocketReconnector(
        connect_fn=connect,
        base_delay_sec=0.01,
        max_delay_sec=0.05,
    )
    reconnector._running = True
    try:
        reconnector._loop()
    except KeyboardInterrupt:
        pass
    assert connected[0]
    assert attempts[0] == 3


def test_notify_user_error_does_not_crash_on_missing_sender():
    from core.resilience import notify_user_error

    # Should not raise even if message_sender is unavailable
    notify_user_error("test_user", RuntimeError("test error"), context="unit test")
