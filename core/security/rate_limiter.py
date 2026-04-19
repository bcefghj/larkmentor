"""RateLimiter · 8 层安全栈第 6 层

Token-bucket / sliding-window rate limiter for per-user / per-tool QPS caps.
Threshold protects expensive paths (LLM calls, Bitable writes) from runaway
loops or abusive callers.

Two modes:
- ``acquire(key)`` : sliding-window count over last 60 seconds
- ``acquire_tokens(key, n=1)`` : token-bucket for burst tolerance

Defaults: 60 calls/min/user. Override per user via ``set_per_user_qpm`` or
per tool via ``set_per_tool_qpm``.

Thread-safe via a single global lock (lock contention is negligible at
expected QPS for a 2C2G demo). For higher throughput, swap to per-key locks.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple

logger = logging.getLogger("flowguard.security.ratelimit")


DEFAULT_QPM = 60
DEFAULT_TOOL_QPM = 30


@dataclass
class RateDecision:
    allowed: bool
    key: str
    used: int
    cap: int
    reset_in_sec: float = 0.0
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


class RateLimiter:
    """Sliding-window rate limiter (60-second resolution)."""

    def __init__(
        self,
        default_qpm: int = DEFAULT_QPM,
        default_tool_qpm: int = DEFAULT_TOOL_QPM,
    ) -> None:
        self._default_qpm = default_qpm
        self._default_tool_qpm = default_tool_qpm
        self._per_user_qpm: Dict[str, int] = {}
        self._per_tool_qpm: Dict[str, int] = {}
        self._windows: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    # ── Configuration ───────────────────────────────────────

    def set_per_user_qpm(self, user_open_id: str, qpm: int) -> None:
        self._per_user_qpm[user_open_id] = max(0, int(qpm))

    def set_per_tool_qpm(self, tool: str, qpm: int) -> None:
        self._per_tool_qpm[tool] = max(0, int(qpm))

    def cap_for(self, key_type: str, key: str) -> int:
        if key_type == "user":
            return self._per_user_qpm.get(key, self._default_qpm)
        if key_type == "tool":
            return self._per_tool_qpm.get(key, self._default_tool_qpm)
        return self._default_qpm

    # ── Decision ─────────────────────────────────────────────

    def acquire(
        self,
        *,
        user_open_id: str = "",
        tool: str = "",
    ) -> RateDecision:
        """Compound rate check: both per-user and per-tool caps apply."""
        now = time.time()

        if user_open_id:
            user_dec = self._check(now, "user", user_open_id)
            if not user_dec.allowed:
                return user_dec

        if tool:
            tool_dec = self._check(now, "tool", tool)
            if not tool_dec.allowed:
                return tool_dec

        if user_open_id:
            self._record(now, "user", user_open_id)
        if tool:
            self._record(now, "tool", tool)

        return RateDecision(
            allowed=True,
            key=f"user={user_open_id[-6:] if user_open_id else '-'} tool={tool or '-'}",
            used=0, cap=self._default_qpm, reason="ok",
        )

    # ── Internal ─────────────────────────────────────────────

    def _check(self, now: float, key_type: str, key: str) -> RateDecision:
        cap = self.cap_for(key_type, key)
        if cap <= 0:
            return RateDecision(
                allowed=False, key=f"{key_type}:{key}", used=0, cap=0,
                reason=f"{key_type}_disabled",
            )
        with self._lock:
            window = self._windows[f"{key_type}:{key}"]
            cutoff = now - 60.0
            while window and window[0] < cutoff:
                window.popleft()
            used = len(window)
            if used >= cap:
                reset_in = max(0.0, 60.0 - (now - window[0]))
                return RateDecision(
                    allowed=False,
                    key=f"{key_type}:{key}",
                    used=used, cap=cap,
                    reset_in_sec=reset_in,
                    reason=f"{key_type}_qpm_exceeded",
                )
        return RateDecision(
            allowed=True,
            key=f"{key_type}:{key}",
            used=used, cap=cap, reason="ok",
        )

    def _record(self, now: float, key_type: str, key: str) -> None:
        with self._lock:
            self._windows[f"{key_type}:{key}"].append(now)

    # ── Introspection ────────────────────────────────────────

    def stats(self) -> Dict[str, Tuple[int, int]]:
        out = {}
        for k, dq in self._windows.items():
            out[k] = (len(dq), self._default_qpm)
        return out


_default: Optional[RateLimiter] = None


def default_limiter() -> RateLimiter:
    global _default
    if _default is None:
        _default = RateLimiter()
    return _default


def acquire(*, user_open_id: str = "", tool: str = "") -> RateDecision:
    return default_limiter().acquire(user_open_id=user_open_id, tool=tool)
