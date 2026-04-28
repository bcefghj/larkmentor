"""Streaming tool executor with read-write lock.

Inspired by Claude Code's ``StreamingToolExecutor``:

* Read-only tools are dispatched in parallel (shared read lock).
* Write-capable tools take the exclusive write lock (serialised).
* Results are captured in submission order.
* Per-tool timeout with clean cancellation.
* Emits events through an optional callback (for Dashboard / CRDT).
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .tool_registry import ToolRegistry, ToolSpec

logger = logging.getLogger("pilot.harness.streaming_exec")


@dataclass
class ToolInvocation:
    call_id: str
    tool: str
    args: Dict[str, Any]
    ctx: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolOutcome:
    call_id: str
    tool: str
    ok: bool
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    started_ts: int = 0
    finished_ts: int = 0
    readonly: bool = False

    @property
    def duration_ms(self) -> int:
        return max(0, (self.finished_ts - self.started_ts))


class _RWLock:
    """Readers-writer lock (readers preference, bounded concurrent readers)."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._readers = 0
        self._writer = False

    def acquire_read(self):
        with self._cond:
            while self._writer:
                self._cond.wait()
            self._readers += 1

    def release_read(self):
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def acquire_write(self):
        with self._cond:
            while self._writer or self._readers > 0:
                self._cond.wait()
            self._writer = True

    def release_write(self):
        with self._cond:
            self._writer = False
            self._cond.notify_all()


class StreamingToolExecutor:
    def __init__(self, registry: ToolRegistry, *, max_parallel_readers: int = 4,
                 emit: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self._reg = registry
        self._lock = _RWLock()
        self._max = max_parallel_readers
        self._emit = emit
        self._pool = cf.ThreadPoolExecutor(max_workers=max_parallel_readers)

    def _fire(self, payload: Dict[str, Any]) -> None:
        if self._emit is None:
            return
        try:
            self._emit(payload)
        except Exception:
            pass

    def dispatch(self, calls: List[ToolInvocation]) -> List[ToolOutcome]:
        """Execute a batch of tool calls respecting read/write semantics.

        Algorithm:
        * Scan in order; group contiguous readonly calls and run concurrently.
        * Write calls execute serially.
        * Results returned in original call order.
        """
        outcomes: Dict[str, ToolOutcome] = {}
        i = 0
        while i < len(calls):
            call = calls[i]
            spec = self._reg.get(call.tool)
            readonly = bool(spec and spec.readonly)
            if readonly:
                batch: List[ToolInvocation] = []
                while i < len(calls):
                    cur = calls[i]
                    cur_spec = self._reg.get(cur.tool)
                    if not (cur_spec and cur_spec.readonly):
                        break
                    batch.append(cur)
                    i += 1
                for o in self._run_read_batch(batch):
                    outcomes[o.call_id] = o
            else:
                outcomes[call.call_id] = self._run_write(call, spec)
                i += 1
        return [outcomes[c.call_id] for c in calls]

    # ── Read batch ──

    def _run_read_batch(self, batch: List[ToolInvocation]) -> List[ToolOutcome]:
        self._lock.acquire_read()
        try:
            futures: Dict[cf.Future, ToolInvocation] = {}
            for call in batch:
                spec = self._reg.get(call.tool)
                fut = self._pool.submit(self._run_one_locked, call, spec)
                futures[fut] = call
            results: List[ToolOutcome] = []
            for fut in cf.as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as exc:
                    results.append(self._err_outcome(futures[fut], str(exc)))
            # Preserve input order.
            order = {c.call_id: idx for idx, c in enumerate(batch)}
            results.sort(key=lambda o: order.get(o.call_id, 0))
            return results
        finally:
            self._lock.release_read()

    # ── Write ──

    def _run_write(self, call: ToolInvocation, spec: Optional[ToolSpec]) -> ToolOutcome:
        self._lock.acquire_write()
        try:
            return self._run_one_locked(call, spec)
        finally:
            self._lock.release_write()

    def _run_one_locked(self, call: ToolInvocation, spec: Optional[ToolSpec]) -> ToolOutcome:
        started = int(time.time() * 1000)
        self._fire({"kind": "tool_started", "tool": call.tool, "call_id": call.call_id, "ts": started})
        if spec is None or spec.fn is None:
            finished = int(time.time() * 1000)
            outcome = ToolOutcome(
                call_id=call.call_id, tool=call.tool,
                ok=False, error=f"tool not registered: {call.tool}",
                started_ts=started, finished_ts=finished, readonly=False,
            )
            self._fire({"kind": "tool_failed", "tool": call.tool, "call_id": call.call_id,
                         "error": outcome.error, "ts": finished})
            return outcome
        timeout = spec.timeout_sec
        try:
            fut = self._pool.submit(spec.fn, call.args, call.ctx)
            result = fut.result(timeout=timeout) or {}
            finished = int(time.time() * 1000)
            outcome = ToolOutcome(
                call_id=call.call_id, tool=call.tool,
                ok=True, result=result, started_ts=started, finished_ts=finished,
                readonly=spec.readonly,
            )
            self._fire({"kind": "tool_done", "tool": call.tool, "call_id": call.call_id,
                         "duration_ms": outcome.duration_ms, "ts": finished})
            return outcome
        except cf.TimeoutError:
            fut.cancel()
            finished = int(time.time() * 1000)
            outcome = ToolOutcome(
                call_id=call.call_id, tool=call.tool,
                ok=False, error=f"timeout after {timeout}s",
                started_ts=started, finished_ts=finished, readonly=spec.readonly,
            )
            self._fire({"kind": "tool_failed", "tool": call.tool, "call_id": call.call_id,
                         "error": outcome.error, "ts": finished})
            return outcome
        except Exception as exc:
            finished = int(time.time() * 1000)
            tb = traceback.format_exc(limit=2)
            outcome = ToolOutcome(
                call_id=call.call_id, tool=call.tool,
                ok=False, error=f"{type(exc).__name__}: {exc}",
                result={"traceback": tb}, started_ts=started, finished_ts=finished,
                readonly=spec.readonly,
            )
            self._fire({"kind": "tool_failed", "tool": call.tool, "call_id": call.call_id,
                         "error": outcome.error, "ts": finished})
            return outcome

    def _err_outcome(self, call: ToolInvocation, msg: str) -> ToolOutcome:
        now = int(time.time() * 1000)
        return ToolOutcome(
            call_id=call.call_id, tool=call.tool,
            ok=False, error=msg, started_ts=now, finished_ts=now,
        )
