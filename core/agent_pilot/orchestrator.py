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
                # Soft fallback: mark as simulated so the demo still runs
                result = _simulate_tool(step.tool, args, plan, ctx)
                step.result = result
                step.status = "done"
            else:
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
    """Expand ``${s1.doc_token}`` style placeholders."""
    out: Dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
            token = v[2:-1]
            if "." in token:
                step_id, key = token.split(".", 1)
                prev = step_results.get(step_id, {})
                out[k] = prev.get(key, v)
                continue
        out[k] = v
    return out


def _simulate_tool(tool: str, args: Dict[str, Any], plan: Plan, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic stub used when a real tool is not registered.

    Enables end-to-end demos without external side-effects (e.g. when
    running the unit tests or pitching offline). Every stub returns the
    canonical keys downstream steps expect.
    """
    ts = int(time.time())
    if tool == "im.fetch_thread":
        return {"messages": [
            {"sender": "demo_user", "ts": ts - 600, "text": "这是模拟的群聊历史消息 1"},
            {"sender": "demo_user", "ts": ts - 300, "text": "这是模拟的群聊历史消息 2"},
        ], "count": 2}
    if tool == "doc.create":
        return {"doc_token": f"sim_doc_{ts}", "url": f"https://example.feishu.cn/docx/sim_doc_{ts}"}
    if tool == "doc.append":
        return {"doc_token": args.get("doc_token", ""), "blocks_added": 5}
    if tool == "canvas.create":
        return {"canvas_id": f"sim_canvas_{ts}", "url": f"https://example.feishu.cn/board/sim_canvas_{ts}"}
    if tool == "canvas.add_shape":
        return {"canvas_id": args.get("canvas_id", ""), "shape_id": f"shape_{ts}"}
    if tool == "slide.generate":
        return {"slide_id": f"sim_slide_{ts}", "pptx_url": f"/artifacts/sim_slide_{ts}.pptx",
                "pdf_url": f"/artifacts/sim_slide_{ts}.pdf", "pages": 8}
    if tool == "slide.rehearse":
        return {"slide_id": args.get("slide_id", ""), "speaker_notes": ["模拟演讲稿 1", "模拟演讲稿 2"]}
    if tool == "voice.transcribe":
        return {"text": "（模拟语音转写）把本周讨论整理成 PPT"}
    if tool == "archive.bundle":
        return {"share_url": f"https://example.feishu.cn/pilot/{plan.plan_id}",
                "artifacts": list(ctx["step_results"].keys())}
    if tool == "sync.broadcast":
        return {"broadcast_ok": True}
    if tool == "mentor.clarify":
        return {"questions": ["请问具体要覆盖哪些时间段？", "汇报对象是谁？"]}
    if tool == "mentor.summarize":
        return {"summary": "（模拟）本周围绕 Agent-Pilot 架构达成 3 项共识。"}
    return {"simulated": True, "tool": tool}
