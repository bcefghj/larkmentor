"""Orchestrator — DAG 执行器.

按照 Anthropic Parallelization 模式：
  - 同 parallel_group 的步骤用 asyncio.gather 并行
  - 不同步骤通过 depends_on 串行
  - 上游 step.result 自动注入下游 args（${sX.field} 占位语法）

用法:

    orch = Orchestrator(tool_dispatcher, on_event=cb)
    await orch.run(plan)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from pilot.runtime.planner import Plan, PlanStep

logger = logging.getLogger("pilot.runtime.orchestrator")


class ToolExecutor(Protocol):
    async def execute(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        ...


@dataclass
class ExecutionEvent:
    kind: str
    step_id: str = ""
    tool: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


EventCallback = Callable[[ExecutionEvent], Awaitable[None]]


PLACEHOLDER_RE = re.compile(r"\$\{([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\}")


def _resolve_placeholders(args: dict[str, Any], step_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """把 ${sX.field} 替换为 step_results[sX][field]."""

    def _replace_in_value(v: Any) -> Any:
        if isinstance(v, str):
            def _sub(m: re.Match[str]) -> str:
                step_id, field_name = m.group(1), m.group(2)
                r = step_results.get(step_id, {})
                if not isinstance(r, dict):
                    return m.group(0)
                value = r.get(field_name, "")
                return str(value) if value is not None else ""
            return PLACEHOLDER_RE.sub(_sub, v)
        if isinstance(v, dict):
            return {k: _replace_in_value(val) for k, val in v.items()}
        if isinstance(v, list):
            return [_replace_in_value(x) for x in v]
        return v

    return {k: _replace_in_value(v) for k, v in args.items()}


class Orchestrator:
    """DAG 执行器."""

    def __init__(
        self,
        tool_executor: ToolExecutor,
        *,
        on_event: EventCallback | None = None,
        max_parallel: int = 4,
    ) -> None:
        self.tool_executor = tool_executor
        self.on_event = on_event
        self.max_parallel = max_parallel
        self._sem: asyncio.Semaphore | None = None

    async def _emit(self, ev: ExecutionEvent) -> None:
        if self.on_event:
            try:
                await self.on_event(ev)
            except Exception as e:
                logger.debug("on_event handler failed: %s", e)

    async def run(self, plan: Plan, *, ctx_extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """执行整个 plan，返回最终结果汇总."""
        self._sem = asyncio.Semaphore(self.max_parallel)
        await self._emit(ExecutionEvent(kind="plan.start", payload={
            "plan_id": plan.plan_id,
            "total_steps": len(plan.steps),
        }))

        step_results: dict[str, dict[str, Any]] = {}
        completed: set[str] = set()
        failed: set[str] = set()

        loop_count = 0
        while True:
            loop_count += 1
            if loop_count > 100:
                logger.warning("orchestrator loop exceeded 100 iterations")
                break

            # ready = 所有 pending 中依赖都已完成的
            ready = [
                s for s in plan.steps
                if s.status == "pending"
                and all(dep in completed for dep in s.depends_on)
            ]
            if not ready:
                # 检查是否还有 pending 但依赖失败的
                pending = [s for s in plan.steps if s.status == "pending"]
                for s in pending:
                    if any(dep in failed for dep in s.depends_on):
                        s.status = "skipped"
                        await self._emit(ExecutionEvent(kind="step.skipped", step_id=s.step_id, tool=s.tool,
                                                        payload={"reason": "upstream_failed"}))
                if not [s for s in plan.steps if s.status == "pending"]:
                    break
                # 否则陷入死锁，退出
                logger.warning("orchestrator deadlock — pending=%d, completed=%d, failed=%d",
                               len(pending), len(completed), len(failed))
                break

            # 按 parallel_group 分组
            groups: dict[str, list[PlanStep]] = {}
            for s in ready:
                key = s.parallel_group or s.step_id  # 没 parallel_group 就单独成组
                groups.setdefault(key, []).append(s)

            # 每组并行执行
            for group_key, group_steps in groups.items():
                if len(group_steps) == 1:
                    await self._exec_step(group_steps[0], step_results, ctx_extra or {}, completed, failed)
                else:
                    await asyncio.gather(*[
                        self._exec_step(s, step_results, ctx_extra or {}, completed, failed)
                        for s in group_steps
                    ])

        await self._emit(ExecutionEvent(kind="plan.done", payload={
            "plan_id": plan.plan_id,
            "completed": len(completed),
            "failed": len(failed),
            "skipped": len([s for s in plan.steps if s.status == "skipped"]),
        }))

        return {
            "plan_id": plan.plan_id,
            "completed": list(completed),
            "failed": list(failed),
            "step_results": step_results,
        }

    async def _exec_step(
        self,
        step: PlanStep,
        step_results: dict[str, dict[str, Any]],
        ctx_extra: dict[str, Any],
        completed: set[str],
        failed: set[str],
    ) -> None:
        assert self._sem is not None
        async with self._sem:
            step.status = "running"
            step.started_ts = int(time.time())
            await self._emit(ExecutionEvent(kind="step.start", step_id=step.step_id, tool=step.tool,
                                            payload={"description": step.description}))

            try:
                resolved_args = _resolve_placeholders(step.args, step_results)
                ctx = {
                    **ctx_extra,
                    "step_id": step.step_id,
                    "step_results": step_results,
                    "resolved_args": resolved_args,
                }
                result = await self.tool_executor.execute(
                    tool_name=step.tool,
                    tool_input=resolved_args,
                    ctx=ctx,
                )
                step.result = result if isinstance(result, dict) else {"value": result}
                step_results[step.step_id] = step.result
                step.status = "done"
                step.finished_ts = int(time.time())
                completed.add(step.step_id)
                await self._emit(ExecutionEvent(kind="step.done", step_id=step.step_id, tool=step.tool,
                                                payload={
                                                    "duration_ms": (step.finished_ts - step.started_ts) * 1000,
                                                    "result_keys": list(step.result.keys())[:8],
                                                }))
            except Exception as e:
                step.status = "failed"
                step.finished_ts = int(time.time())
                step.error = str(e)
                failed.add(step.step_id)
                logger.exception("step %s failed: %s", step.step_id, e)
                await self._emit(ExecutionEvent(kind="step.failed", step_id=step.step_id, tool=step.tool,
                                                payload={"error": str(e)[:200]}))
