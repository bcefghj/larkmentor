"""Pilot Orchestrator – executes a Plan and broadcasts every event.

The orchestrator is deliberately synchronous and in-process so it can
run inside the existing lark-oapi message callback. For long-running
tool calls (slide export, whisper STT) we spawn a thread and stream
progress events back through the CRDT hub.

Execution contract
------------------
* Steps are executed in **topological order** respecting ``depends_on``.
* Steps sharing a ``parallel_group`` run concurrently in a thread pool.
* Every state change emits an ``ExecutionEvent`` that is:
    1. appended to the plan's internal log (for replay / debug);
    2. pushed to the CRDT hub (``sync.broadcast``) so all clients update;
    3. optionally echoed into flow_memory.archival for long-term trace.
* Tool functions live in ``agent_pilot/tools/``; each returns a dict
  result and raises on hard error. The orchestrator serialises exceptions
  into ``step.error`` and keeps going for non-critical failures (tool
  metadata can mark a tool as critical).
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

from .planner import Plan, PlanStep

logger = logging.getLogger("pilot.orchestrator")


class ToolNotRegisteredError(RuntimeError):
    """Raised when the orchestrator encounters a tool name with no callable.

    P1.1 design choice: in the past we silently simulated. That made
    production failures invisible. Now we bubble up so the verify/reflect
    loop can retry or replan.
    """


@dataclass
class ExecutionEvent:
    event_id: str
    plan_id: str
    kind: str                  # plan_started / step_started / step_done / step_failed / plan_done
    step_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


ToolFn = Callable[[PlanStep, Dict[str, Any]], Dict[str, Any]]


class PilotOrchestrator:

    def __init__(
        self,
        *,
        tool_registry: Optional[Dict[str, ToolFn]] = None,
        broadcaster: Optional[Callable[[ExecutionEvent], None]] = None,
        max_parallel: int = 4,
    ):
        self._tools = tool_registry or {}
        self._broadcaster = broadcaster
        self._max_parallel = max_parallel
        self._events: List[ExecutionEvent] = []
        self._lock = threading.Lock()

    # ── Registration ──

    def register_tool(self, name: str, fn: ToolFn) -> None:
        self._tools[name] = fn

    def set_broadcaster(self, fn: Callable[[ExecutionEvent], None]) -> None:
        self._broadcaster = fn

    # ── Event bus ──

    def _emit(self, ev: ExecutionEvent) -> None:
        with self._lock:
            self._events.append(ev)
        if self._broadcaster is not None:
            try:
                self._broadcaster(ev)
            except Exception as e:
                logger.debug("broadcaster failed: %s", e)

    def events(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._events]

    # ── Execution ──

    def run(self, plan: Plan, *, context: Optional[Dict[str, Any]] = None) -> Plan:
        """Execute the whole plan. Returns the same Plan with statuses filled."""
        ctx: Dict[str, Any] = dict(context or {})
        ctx.setdefault("plan_id", plan.plan_id)
        ctx.setdefault("user_open_id", plan.user_open_id)
        ctx.setdefault("step_results", {})  # step_id -> dict

        self._emit(ExecutionEvent(
            event_id=f"ev_{int(time.time()*1000)}",
            plan_id=plan.plan_id,
            kind="plan_started",
            payload={"intent": plan.intent, "total_steps": len(plan.steps)},
            ts=int(time.time()),
        ))

        # Main loop: repeatedly pick ready steps and run them, parallel when possible.
        while True:
            ready = plan.ready_steps()
            if not ready:
                break

            # Group by parallel_group so we run groups concurrently.
            groups: Dict[str, List[PlanStep]] = {}
            singles: List[PlanStep] = []
            for s in ready:
                if s.parallel_group:
                    groups.setdefault(s.parallel_group, []).append(s)
                else:
                    singles.append(s)

            for s in singles:
                self._run_step(s, plan, ctx)

            for group_key, group_steps in groups.items():
                if len(group_steps) == 1:
                    self._run_step(group_steps[0], plan, ctx)
                    continue
                with ThreadPoolExecutor(max_workers=min(self._max_parallel, len(group_steps))) as pool:
                    futures = {pool.submit(self._run_step, s, plan, ctx): s for s in group_steps}
                    for fut in as_completed(futures):
                        fut.result()  # exceptions already captured in step.error

            # Safety: if nothing made progress in this pass, break
            still_pending = [s for s in plan.steps if s.status == "pending"]
            just_ran = [s for s in ready if s.status in ("done", "failed")]
            if still_pending and not just_ran:
                logger.warning("orchestrator stuck, bailing out")
                break

        self._emit(ExecutionEvent(
            event_id=f"ev_{int(time.time()*1000)}",
            plan_id=plan.plan_id,
            kind="plan_done",
            payload={
                "total": len(plan.steps),
                "done": sum(1 for s in plan.steps if s.status == "done"),
                "failed": sum(1 for s in plan.steps if s.status == "failed"),
            },
            ts=int(time.time()),
        ))
        return plan

    # ── Single step ──

    def _run_step(self, step: PlanStep, plan: Plan, ctx: Dict[str, Any]) -> None:
        step.status = "running"
        step.started_ts = int(time.time())
        self._emit(ExecutionEvent(
            event_id=f"ev_{int(time.time()*1000)}",
            plan_id=plan.plan_id,
            kind="step_started",
            step_id=step.step_id,
            payload={"tool": step.tool, "description": step.description},
            ts=step.started_ts,
        ))

        # Resolve ${s1.key} placeholders in args using previous results
        args = _resolve_args(step.args or {}, ctx["step_results"])

        tool_fn = self._tools.get(step.tool)
        try:
            if tool_fn is None:
                # P1.1: No silent simulation. Missing tools MUST raise so the
                # upper layer records a failure and triggers verify → replan.
                raise ToolNotRegisteredError(
                    f"tool not registered: {step.tool}. "
                    f"Register it in core/agent_pilot/tools or via harness MCPClient."
                )
            result = tool_fn(step, {**ctx, "resolved_args": args}) or {}
            step.result = result
            step.status = "done"
        except Exception as e:
            logger.exception("step %s failed", step.step_id)
            step.status = "failed"
            step.error = f"{type(e).__name__}: {e}"
            step.result = {"error": step.error, "traceback": traceback.format_exc(limit=3)}

        step.finished_ts = int(time.time())
        ctx["step_results"][step.step_id] = step.result or {}

        self._emit(ExecutionEvent(
            event_id=f"ev_{int(time.time()*1000)}",
            plan_id=plan.plan_id,
            kind="step_done" if step.status == "done" else "step_failed",
            step_id=step.step_id,
            payload={
                "tool": step.tool,
                "result": step.result,
                "duration_ms": (step.finished_ts - step.started_ts) * 1000,
                "error": step.error,
            },
            ts=step.finished_ts,
        ))


def _resolve_args(args: Dict[str, Any], step_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Expand step-result placeholders in tool arguments.

    Supported formats (LLMs emit all of these):
      ${s1.doc_token}           → step_results["s1"]["doc_token"]
      {{s3.result.doc_token}}   → step_results["s3"]["doc_token"]  (strips "result.")
      {{s3.doc_token}}          → step_results["s3"]["doc_token"]
    """
    import re
    _PLACEHOLDER = re.compile(r"^\$\{(.+?)\}$|^\{\{(.+?)\}\}$")

    out: Dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str):
            m = _PLACEHOLDER.match(v.strip())
            if m:
                token = (m.group(1) or m.group(2) or "").strip()
                token = re.sub(r"\.result\.", ".", token)
                if "." in token:
                    step_id, key = token.split(".", 1)
                    prev = step_results.get(step_id, {})
                    out[k] = prev.get(key, v)
                    continue
        out[k] = v
    return out


# P1.1: the legacy _simulate_tool fallback has been removed on purpose.
# All failures now propagate as ToolNotRegisteredError and the orchestrator
# (or the new ConversationOrchestrator) classifies them for verify/replan.

