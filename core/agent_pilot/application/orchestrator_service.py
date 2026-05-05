"""OrchestratorService · Task State Machine Adapter.

Bridges the domain Task lifecycle with the unified ConversationOrchestrator.

Responsibilities:
1. Advance the Task state machine based on plan execution progress
2. Log every step result to ``Task.log(...)`` for audit trail
3. Fire domain events via ``EventBus`` for downstream listeners
4. Delegate actual tool execution to the harness ConversationOrchestrator
   (or run inline when the harness is unavailable, e.g. in unit tests)

Design:
- This is NOT an independent execution engine. It wraps the harness orchestrator
  and adds domain-level state machine transitions on top.
- For unit tests, tools can be injected directly via the ``tools`` parameter.
- State machine transitions:
  ``PLAN_DONE_DOC`` → DOC_GENERATING
  ``GENERATION_DONE`` → REVIEWING
  ``USER_DELIVER`` → DELIVERED (user-driven)
"""

from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

try:
    from core.observability import audit, incr, observe, span, trace_tool_call
except ImportError:
    from contextlib import contextmanager as _cm

    def audit(*a: Any, **kw: Any) -> None: ...
    def incr(*a: Any, **kw: Any) -> None: ...
    def observe(*a: Any, **kw: Any) -> None: ...

    @_cm
    def span(*a: Any, **kw: Any):  # type: ignore[misc]
        yield None

    @_cm
    def trace_tool_call(*a: Any, **kw: Any):  # type: ignore[misc]
        yield None

from ..domain import (
    Plan as DomainPlan,
)
from ..domain import (
    PlanStep as DomainPlanStep,
)
from ..domain import (
    Task,
    TaskEvent,
    TaskState,
)
from ..domain.events import (
    EVT_PLAN_CREATED,
    EVT_STEP_DONE,
    EVT_STEP_FAILED,
    EVT_STEP_STARTED,
    EventBus,
    default_event_bus,
    make_event,
)

logger = logging.getLogger("pilot.application.orchestrator_service")


def _default_llm_fn(prompt: str) -> str:
    """Try providers -> llm_client -> return empty.

    Uses the multi-provider router with circuit breaker and auto-fallback.
    If all providers are unavailable, falls back to the basic ARK client.
    """
    try:
        from agent.providers import default_providers

        router = default_providers()
        return router.chat(
            messages=[{"role": "user", "content": prompt}],
            task_kind="chinese_chat",
            max_tokens=2000,
        )
    except Exception as e:
        logger.debug("default_llm_fn providers fallback: %s", e)
    try:
        from llm.llm_client import chat as _chat

        return _chat(prompt, temperature=0.4)
    except Exception as e:
        logger.debug("default_llm_fn llm_client fallback: %s", e)
        return ""


def _fallback_doc_content(intent: str, ctx: Dict[str, Any]) -> str:
    plan_id = ctx.get("plan_id", "")
    return (
        f"## 背景与目标\n\n"
        f"本文档由 Agent-Pilot 计划 `{plan_id}` 自动生成。\n\n"
        f"任务目标：{intent}\n\n"
        f"## 核心内容\n\n"
        f"（Agent 正在分析上下文并生成内容...）\n\n"
        f"## 下一步行动\n\n"
        f"- [ ] 评审文档内容\n"
        f"- [ ] 补充细节\n"
        f"- [ ] 确认后转为 PPT\n"
    )


# tool function: (step, ctx) -> dict
ToolFn = Callable[[DomainPlanStep, Dict[str, Any]], Dict[str, Any]]


@dataclass
class OrchestratorConfig:
    max_parallel: int = 4
    fail_fast: bool = False
    max_retry_per_step: int = 1
    demo_mode: bool = False
    step_timeout_sec: int = 120
    plan_timeout_sec: int = 600


class OrchestratorService:
    def __init__(
        self,
        *,
        tools: Optional[Dict[str, ToolFn]] = None,
        event_bus: Optional[EventBus] = None,
        config: Optional[OrchestratorConfig] = None,
        llm_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._tools: Dict[str, ToolFn] = dict(tools or {})
        self.bus = event_bus or default_event_bus()
        self.cfg = config or OrchestratorConfig()
        if os.environ.get("AGENT_PILOT_DEMO_MODE", "").lower() in ("1", "true", "yes"):
            self.cfg.demo_mode = True
        self._lock = threading.Lock()
        self._llm_fn = llm_fn or _default_llm_fn
        self._broadcaster: Optional[Callable] = None

    @property
    def orchestrator(self) -> "OrchestratorService":
        return self

    def set_broadcaster(self, fn: Callable) -> None:
        self._broadcaster = fn

    def _broadcast(self, kind: str, plan_id: str, step_id: str = "", payload: Optional[Dict[str, Any]] = None) -> None:
        if self._broadcaster is not None:
            try:
                self._broadcaster({"kind": kind, "plan_id": plan_id, "step_id": step_id, "payload": payload or {}})
            except Exception as e:
                logger.debug("broadcaster failed: %s", e)

    def _broadcast_progress(self, plan: DomainPlan) -> None:
        """Emit a progress event with percentage completion."""
        total = plan.step_count()
        done = sum(1 for s in plan.steps if s.status in ("done", "failed"))
        pct = int((done / total) * 100) if total > 0 else 0
        self._broadcast(
            "progress",
            plan_id=plan.plan_id,
            payload={
                "done": done,
                "total": total,
                "percent": pct,
                "running": [s.step_id for s in plan.steps if s.status == "running"],
            },
        )

    def register_tool(self, name: str, fn: ToolFn) -> None:
        self._tools[name] = fn

    # ── 执行入口 ──────────────────────────────────────────────────────────
    def run(self, task: Task, *, advance_state: bool = True) -> Task:
        plan = task.plan
        if plan is None or not plan.steps:
            raise ValueError("Task.plan must be a non-empty DomainPlan")

        incr("pilot_requests_total", source="orchestrator", status="started")
        audit("plan_started", task_id=task.task_id, plan_id=plan.plan_id, step_count=plan.step_count())

        # 状态机：进入第一档 generating（按 ContextPack.output_requirements 决定）
        if advance_state and task.state == TaskState.PLANNING:
            primary = task.context_pack.output_requirements.primary if task.context_pack else "doc"
            evt = {
                "doc": TaskEvent.PLAN_DONE_DOC,
                "ppt": TaskEvent.PLAN_DONE_PPT,
                "canvas": TaskEvent.PLAN_DONE_CANVAS,
            }.get(primary, TaskEvent.PLAN_DONE_DOC)
            try:
                task.apply(
                    evt, actor_open_id=task.owner_lock.owner_open_id, event_bus=self.bus, enforce_owner_lock=False
                )
            except Exception as e:
                logger.warning("state advance to generating failed: %s", e)

        self.bus.publish(
            make_event(
                EVT_PLAN_CREATED,
                task.task_id,
                data={
                    "plan_id": plan.plan_id,
                    "step_count": plan.step_count(),
                    "reasoning_pattern": plan.reasoning_pattern,
                },
            )
        )

        ctx: Dict[str, Any] = {
            "task_id": task.task_id,
            "plan_id": plan.plan_id,
            "owner_open_id": plan.owner_open_id,
            "step_results": {},
            "context_pack": task.context_pack,
        }

        self._broadcast(
            "plan_started",
            plan_id=plan.plan_id,
            payload={
                "intent": task.intent,
                "total_steps": plan.step_count(),
                "reasoning_pattern": plan.reasoning_pattern,
            },
        )

        # 主循环：拓扑就绪即跑，parallel_group 并发
        plan_start_ts = time.time()
        while True:
            # Plan-level timeout check
            if time.time() - plan_start_ts > self.cfg.plan_timeout_sec:
                logger.warning("plan timeout after %ds", self.cfg.plan_timeout_sec)
                self._broadcast(
                    "plan_timeout",
                    plan_id=plan.plan_id,
                    payload={"timeout_sec": self.cfg.plan_timeout_sec},
                )
                break

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
                self._broadcast_progress(plan)
                if self.cfg.fail_fast and s.status == "failed":
                    self._finalize_failure(task, s.error)
                    return task

            for grp, gs in groups.items():
                if len(gs) == 1:
                    self._run_step(gs[0], task, ctx)
                    self._broadcast_progress(plan)
                    continue
                with ThreadPoolExecutor(max_workers=min(self.cfg.max_parallel, len(gs))) as pool:
                    futs = {pool.submit(self._run_step, s, task, ctx): s for s in gs}
                    for fut in as_completed(futs):
                        fut.result()
                self._broadcast_progress(plan)
            # safety
            still_pending = [s for s in plan.steps if s.status == "pending"]
            just_ran = [s for s in ready if s.status in ("done", "failed")]
            if still_pending and not just_ran:
                logger.warning("orchestrator stuck — pending steps depend on failed ones")
                break

        self._broadcast(
            "plan_done",
            plan_id=plan.plan_id,
            payload={
                "done": sum(1 for s in plan.steps if s.status == "done"),
                "failed": sum(1 for s in plan.steps if s.status == "failed"),
                "total": plan.step_count(),
            },
        )

        # 状态推进 → REVIEWING
        if advance_state and task.state.is_generating:
            try:
                task.apply(
                    TaskEvent.GENERATION_DONE,
                    actor_open_id=task.owner_lock.owner_open_id,
                    event_bus=self.bus,
                    enforce_owner_lock=False,
                )
            except Exception as e:
                logger.warning("state advance to REVIEWING failed: %s", e)

        return task

    # ── 单步执行 ─────────────────────────────────────────────────────────
    def _run_step(self, step: DomainPlanStep, task: Task, ctx: Dict[str, Any]) -> None:
        step.status = "running"
        step.started_ts = int(time.time())
        self.bus.publish(
            make_event(
                EVT_STEP_STARTED,
                task.task_id,
                data={"step_id": step.step_id, "tool": step.tool},
                ts=step.started_ts,
            )
        )
        self._broadcast(
            "step_started",
            plan_id=ctx.get("plan_id", ""),
            step_id=step.step_id,
            payload={"tool": step.tool, "description": step.description},
        )
        task.log(
            agent="@pilot", kind="tool_call", content=f"{step.tool}({step.description})", meta={"step_id": step.step_id}
        )

        args = self._resolve_args(step.args or {}, ctx["step_results"])

        # LLM content enrichment for doc/slide generation
        if step.tool == "doc.append" and not args.get("markdown"):
            args["markdown"] = self._enrich_doc_content(task, ctx)
        elif step.tool == "slide.generate" and not args.get("outline"):
            args["outline"] = self._enrich_slide_outline(task, ctx)

        tool_fn = self._tools.get(step.tool)
        if tool_fn is None:
            if self.cfg.demo_mode:
                logger.warning("tool not registered (demo_mode=True, simulating): %s", step.tool)
                step.result = {"simulated": True, "tool": step.tool, "args": args}
                step.status = "done"
                step.error = ""
            else:
                logger.error("tool not registered: %s", step.tool)
                step.status = "failed"
                step.error = f"tool_not_registered: {step.tool}"
                step.result = {"error": step.error}
        else:
            with trace_tool_call(step.tool, args):
                try:
                    result = tool_fn(step, {**ctx, "resolved_args": args}) or {}
                    step.result = result
                    step.status = "done"
                except Exception as e:
                    logger.exception("step %s failed: %s", step.step_id, e)
                    step.status = "failed"
                    step.error = f"{type(e).__name__}: {e}"
                    step.result = {"error": step.error, "traceback": traceback.format_exc(limit=3)}

        step.finished_ts = int(time.time())
        ctx["step_results"][step.step_id] = step.result or {}

        evt_kind = EVT_STEP_DONE if step.status == "done" else EVT_STEP_FAILED
        self.bus.publish(
            make_event(
                evt_kind,
                task.task_id,
                data={
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "duration_ms": (step.finished_ts - step.started_ts) * 1000,
                    "error": step.error,
                },
                ts=step.finished_ts,
            )
        )
        broadcast_kind = "step_done" if step.status == "done" else "step_failed"
        self._broadcast(
            broadcast_kind,
            plan_id=ctx.get("plan_id", ""),
            step_id=step.step_id,
            payload={
                "tool": step.tool,
                "duration_ms": (step.finished_ts - step.started_ts) * 1000,
                "error": step.error,
            },
        )
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

    def _enrich_doc_content(self, task: Task, ctx: Dict[str, Any]) -> str:
        if self.cfg.demo_mode:
            return _fallback_doc_content(task.intent, ctx)

        cp = task.context_pack
        source_text = ""
        if cp and cp.source_messages:
            source_text = "\n".join(f"- {m.sender_open_id}: {m.text}" for m in cp.source_messages[:10])
        prompt = (
            f"你是 Agent-Pilot，一个专业的文档生成助手。\n\n"
            f"任务目标：{task.intent}\n\n"
            f"上下文信息：\n{source_text or '(无额外上下文)'}\n\n"
            f"请生成一份结构化的 Markdown 文档，包含：\n"
            f"1. 背景与目标\n2. 核心内容\n3. 下一步行动\n\n"
            f"要求：专业、简洁、可执行。直接输出 Markdown 内容，不要包含任何额外说明。"
        )
        result = self._llm_fn(prompt)
        return result if result else _fallback_doc_content(task.intent, ctx)

    def _enrich_slide_outline(self, task: Task, ctx: Dict[str, Any]) -> str:
        if self.cfg.demo_mode:
            return [
                {"title": "项目背景与目标", "bullets": ["团队痛点分析", "解决方案概述", "预期收益"]},
                {"title": "核心方案", "bullets": ["技术架构", "关键模块设计", "实现路径"]},
                {"title": "时间规划", "bullets": ["第一阶段: 基础搭建", "第二阶段: 功能迭代", "第三阶段: 上线运营"]},
                {"title": "总结与下一步", "bullets": ["核心成果回顾", "待确认事项", "行动计划"]},
            ]

        step_results = ctx.get("step_results") or {}
        doc_content = ""
        for r in step_results.values():
            if isinstance(r, dict) and r.get("source") in ("feishu", "local_markdown"):
                path = r.get("path", "")
                if path and os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            doc_content = f.read()[:3000]
                    except Exception as e:
                        logger.debug("read doc content for slide outline failed: %s", e)
        prompt = (
            f"你是 Agent-Pilot，一个专业的演示文稿规划助手。\n\n"
            f"任务目标：{task.intent}\n\n"
            f"文档内容摘要：\n{doc_content or '(无已有文档内容)'}\n\n"
            f"请生成一个 6-8 页的 PPT 大纲，每页包含标题和 3-4 个要点。\n"
            f'输出格式为 JSON 数组：[{{"title": "...", "bullets": ["..."]}}]\n'
            f"直接输出 JSON，不要包含 markdown 代码块标记。"
        )
        result = self._llm_fn(prompt)
        if result:
            import json as _json

            try:
                cleaned = result.strip()
                if cleaned.startswith("```"):
                    cleaned = "\n".join(cleaned.split("\n")[1:])
                    if cleaned.endswith("```"):
                        cleaned = cleaned[:-3]
                return _json.loads(cleaned.strip())
            except Exception as e:
                logger.debug("slide outline JSON parse failed: %s", e)
        return ""

    def _finalize_failure(self, task: Task, error: str) -> None:
        try:
            task.apply(
                TaskEvent.FATAL_ERROR,
                actor_open_id="system",
                note=f"orchestrator: {error}",
                event_bus=self.bus,
                enforce_owner_lock=False,
            )
        except Exception:
            pass


__all__ = ["OrchestratorService", "OrchestratorConfig"]
