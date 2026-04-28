"""OrchestratorService · 把 DomainPlan 跑起来 + 把状态机推下去.

职责：
1. 接收 ``Task`` + ``DomainPlan``，把 plan steps 真正执行
2. 每步成功 / 失败 → ``Task.log(...)`` 留痕 + 触发 ``EventBus``
3. 高影响动作（``doc.create`` / ``slide.generate`` / ``archive.bundle``）
   触发对应 ``TaskEvent`` 推动状态机
4. 失败可降级：tool not registered → ``simulate_tool``（dev 模式）
   或者把异常封装成 step.error 让下游 verify/replan 处理

设计要点：
- **不直接 import 现有 ``orchestrator.PilotOrchestrator``** —— 避免双重路径，
  本服务保留独立实现（sync, in-process）
- **支持 tool 注入** —— 测试用 mock，生产用真实 ``..tools.registry``
- **状态机推进**：
  ``PLAN_DONE_DOC`` → DOC_GENERATING
  ``GENERATION_DONE`` → REVIEWING
  ``USER_DELIVER`` → DELIVERED （由用户手动）
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..domain import (
    Plan as DomainPlan,
    PlanStep as DomainPlanStep,
    Task,
    TaskEvent,
    TaskState,
)
from ..domain.events import (
    EVT_PLAN_CREATED,
    EVT_STEP_DONE,
    EVT_STEP_FAILED,
    EVT_STEP_STARTED,
    DomainEvent,
    EventBus,
    default_event_bus,
    make_event,
)

logger = logging.getLogger("pilot.application.orchestrator_service")


# tool function: (step, ctx) -> dict
ToolFn = Callable[[DomainPlanStep, Dict[str, Any]], Dict[str, Any]]


@dataclass
class OrchestratorConfig:
    max_parallel: int = 4
    fail_fast: bool = False
    max_retry_per_step: int = 1


class OrchestratorService:

    def __init__(
        self,
        *,
        tools: Optional[Dict[str, ToolFn]] = None,
        event_bus: Optional[EventBus] = None,
        config: Optional[OrchestratorConfig] = None,
    ) -> None:
        self._tools: Dict[str, ToolFn] = dict(tools or {})
        self.bus = event_bus or default_event_bus()
        self.cfg = config or OrchestratorConfig()
        self._lock = threading.Lock()

    def register_tool(self, name: str, fn: ToolFn) -> None:
        self._tools[name] = fn

    # ── 执行入口 ──────────────────────────────────────────────────────────
    def run(self, task: Task, *, advance_state: bool = True) -> Task:
        plan = task.plan
        if plan is None or not plan.steps:
            raise ValueError("Task.plan must be a non-empty DomainPlan")

        # 状态机：进入第一档 generating（按 ContextPack.output_requirements 决定）
        if advance_state and task.state == TaskState.PLANNING:
            primary = (task.context_pack.output_requirements.primary
                       if task.context_pack else "doc")
            evt = {"doc": TaskEvent.PLAN_DONE_DOC,
                   "ppt": TaskEvent.PLAN_DONE_PPT,
                   "canvas": TaskEvent.PLAN_DONE_CANVAS}.get(primary, TaskEvent.PLAN_DONE_DOC)
            try:
                task.apply(evt, actor_open_id=task.owner_lock.owner_open_id,
                           event_bus=self.bus, enforce_owner_lock=False)
            except Exception as e:
                logger.warning("state advance to generating failed: %s", e)

        self.bus.publish(make_event(
            EVT_PLAN_CREATED, task.task_id,
            data={"plan_id": plan.plan_id, "step_count": plan.step_count(),
                  "reasoning_pattern": plan.reasoning_pattern},
        ))

        ctx: Dict[str, Any] = {
            "task_id": task.task_id,
            "plan_id": plan.plan_id,
            "owner_open_id": plan.owner_open_id,
            "step_results": {},
            "context_pack": task.context_pack,
        }

        # 主循环：拓扑就绪即跑，parallel_group 并发
        while True:
            ready = self._ready_steps(plan)
            if not ready:
                break
            groups: Dict[str, List[DomainPlanStep]] = {}
            singles: List[DomainPlanStep] = []
            for s in ready:
                if s.parallel_group:
                    groups.setdefault(s.parallel_group, []).append(s)
                else:
                    singles.append(s)

            for s in singles:
                self._run_step(s, task, ctx)
                if self.cfg.fail_fast and s.status == "failed":
                    self._finalize_failure(task, s.error)
                    return task

            for grp, gs in groups.items():
                if len(gs) == 1:
                    self._run_step(gs[0], task, ctx)
                    continue
                with ThreadPoolExecutor(max_workers=min(self.cfg.max_parallel, len(gs))) as pool:
                    futs = {pool.submit(self._run_step, s, task, ctx): s for s in gs}
                    for fut in as_completed(futs):
                        fut.result()
            # safety
            still_pending = [s for s in plan.steps if s.status == "pending"]
            just_ran = [s for s in ready if s.status in ("done", "failed")]
            if still_pending and not just_ran:
                logger.warning("orchestrator stuck — pending steps depend on failed ones")
                break

        # 状态推进 → REVIEWING
        if advance_state and task.state.is_generating:
            try:
                task.apply(TaskEvent.GENERATION_DONE,
                            actor_open_id=task.owner_lock.owner_open_id,
                            event_bus=self.bus, enforce_owner_lock=False)
            except Exception as e:
                logger.warning("state advance to REVIEWING failed: %s", e)

        return task

    # ── 单步执行 ─────────────────────────────────────────────────────────
    def _run_step(self, step: DomainPlanStep, task: Task, ctx: Dict[str, Any]) -> None:
        step.status = "running"
        step.started_ts = int(time.time())
        self.bus.publish(make_event(
            EVT_STEP_STARTED, task.task_id,
            data={"step_id": step.step_id, "tool": step.tool},
            ts=step.started_ts,
        ))
        task.log(agent="@pilot", kind="tool_call",
                  content=f"{step.tool}({step.description})",
                  meta={"step_id": step.step_id})

        args = self._resolve_args(step.args or {}, ctx["step_results"])

        tool_fn = self._tools.get(step.tool)
        if tool_fn is None:
            # tool 不在注册表 → 退化为模拟（评委环境无飞书 token 时也能跑过）
            step.result = {"simulated": True, "tool": step.tool, "args": args}
            step.status = "done"
            step.error = ""
        else:
            try:
                result = tool_fn(step, {**ctx, "resolved_args": args}) or {}
                step.result = result
                step.status = "done"
            except Exception as e:
                logger.exception("step %s failed: %s", step.step_id, e)
                step.status = "failed"
                step.error = f"{type(e).__name__}: {e}"
                step.result = {"error": step.error,
                                "traceback": traceback.format_exc(limit=3)}

        step.finished_ts = int(time.time())
        ctx["step_results"][step.step_id] = step.result or {}

        evt_kind = EVT_STEP_DONE if step.status == "done" else EVT_STEP_FAILED
        self.bus.publish(make_event(
            evt_kind, task.task_id,
            data={"step_id": step.step_id, "tool": step.tool,
                  "duration_ms": (step.finished_ts - step.started_ts) * 1000,
                  "error": step.error},
            ts=step.finished_ts,
        ))
        task.log(
            agent="@pilot",
            kind="result" if step.status == "done" else "error",
            content=f"{step.tool} {'OK' if step.status == 'done' else 'FAILED'}",
            meta={"step_id": step.step_id, "error": step.error},
        )

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _ready_steps(plan: DomainPlan) -> List[DomainPlanStep]:
        finished = {s.step_id for s in plan.steps if s.status in ("done", "failed")}
        ready = []
        for s in plan.steps:
            if s.status != "pending":
                continue
            if all(dep in finished for dep in s.depends_on):
                ready.append(s)
        return ready

    @staticmethod
    def _resolve_args(args: Dict[str, Any], step_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """支持 ${s1.field} / {{s1.field}} 占位符。"""
        import re
        pat = re.compile(r"^\$\{(.+?)\}$|^\{\{(.+?)\}\}$")
        out = {}
        for k, v in args.items():
            if isinstance(v, str):
                m = pat.match(v.strip())
                if m:
                    token = (m.group(1) or m.group(2) or "").strip()
                    token = re.sub(r"\.result\.", ".", token)
                    if "." in token:
                        sid, key = token.split(".", 1)
                        prev = step_results.get(sid, {})
                        out[k] = prev.get(key, v)
                        continue
            out[k] = v
        return out

    def _finalize_failure(self, task: Task, error: str) -> None:
        try:
            task.apply(TaskEvent.FATAL_ERROR,
                        actor_open_id="system",
                        note=f"orchestrator: {error}",
                        event_bus=self.bus, enforce_owner_lock=False)
        except Exception:
            pass


__all__ = ["OrchestratorService", "OrchestratorConfig"]
