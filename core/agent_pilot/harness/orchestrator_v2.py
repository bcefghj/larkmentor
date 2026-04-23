"""Claude Code-style Agent Loop: gather → plan → dispatch → verify → reflect → replan.

Pipeline (LangGraph semantics, implemented as a state machine when LangGraph
is not available):

    ┌──────────────────┐
    │ gather_context   │ ← fires SessionStart + UserPromptSubmit hooks
    └────────┬─────────┘
             ▼
    ┌──────────────────┐
    │ plan             │ ← LLM / heuristic produces Plan DAG
    └────────┬─────────┘
             ▼
    ┌──────────────────┐
    │ dispatch_tools   │ ← PreToolUse hooks + PermissionGate + StreamingExecutor
    └────────┬─────────┘
             ▼
    ┌──────────────────┐
    │ verify           │ ← concrete-rule checks (all artifacts present?)
    └────────┬─────────┘
             ▼
    ┌──────────────────┐
    │ reflect          │ ← failure classification: retryable? → replan or finish
    └───┬──────────────┘
        │ failed & replans < 3        │ else
        ▼                             ▼
    (loop to plan)              ┌──────────────────┐
                                │ finish           │ ← fires Stop hook
                                └──────────────────┘

The orchestrator is backwards-compatible with the legacy PilotOrchestrator:
its ``run(plan)`` method can be used as a drop-in replacement once a
``Plan`` has been built by the existing planner.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..planner import Plan, PlanStep
from .tool_registry import ToolRegistry, default_registry
from .hooks import HookRegistry, HookEvent, default_hook_registry
from .permissions import PermissionGate, default_permission_gate, PermissionMode, Decision
from .context_manager import ContextManager
from .memory import MemoryLayer, default_memory
from .skills_loader import SkillsLoader, default_skills
from .streaming_executor import StreamingToolExecutor, ToolInvocation, ToolOutcome

logger = logging.getLogger("pilot.harness.orchestrator_v2")


@dataclass
class OrchestratorEvent:
    event_id: str
    plan_id: str
    kind: str
    step_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: int = 0


@dataclass
class OrchestratorState:
    plan: Plan
    step_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    replans: int = 0
    max_replans: int = 3
    finished: bool = False
    verdict: str = ""        # "ok" / "partial" / "failed"
    summary: str = ""


class ConversationOrchestrator:
    """Main agent loop. Replaces the legacy PilotOrchestrator gradually."""

    def __init__(
        self,
        *,
        tools: Optional[ToolRegistry] = None,
        hooks: Optional[HookRegistry] = None,
        permissions: Optional[PermissionGate] = None,
        context: Optional[ContextManager] = None,
        memory: Optional[MemoryLayer] = None,
        skills: Optional[SkillsLoader] = None,
        broadcaster: Optional[Callable[[OrchestratorEvent], None]] = None,
        planner_fn: Optional[Callable[[str, Dict[str, Any]], Plan]] = None,
    ) -> None:
        self._tools = tools or default_registry()
        self._hooks = hooks or default_hook_registry()
        self._perm = permissions or default_permission_gate()
        self._ctxm = context or ContextManager(
            on_pre_compact=lambda ev, msgs: self._hooks.fire(
                HookEvent.PRE_COMPACT, {"event": ev, "message_count": len(msgs)})
        )
        self._mem = memory or default_memory()
        self._skills = skills or default_skills()
        self._broadcaster = broadcaster
        self._planner_fn = planner_fn
        self._events: List[OrchestratorEvent] = []
        self._lock = threading.RLock()
        self._executor = StreamingToolExecutor(
            self._tools, emit=self._on_tool_event,
        )

    # ── Event bus ──

    def set_broadcaster(self, fn: Callable[[OrchestratorEvent], None]) -> None:
        self._broadcaster = fn

    def _emit(self, kind: str, *, plan_id: str = "", step_id: str = "",
              payload: Optional[Dict[str, Any]] = None) -> None:
        ev = OrchestratorEvent(
            event_id=f"ev_{int(time.time()*1000)}_{uuid.uuid4().hex[:4]}",
            plan_id=plan_id, kind=kind, step_id=step_id,
            payload=payload or {}, ts=int(time.time()),
        )
        with self._lock:
            self._events.append(ev)
        if self._broadcaster is not None:
            try:
                self._broadcaster(ev)
            except Exception as exc:
                logger.debug("broadcaster failed: %s", exc)

    def _on_tool_event(self, payload: Dict[str, Any]) -> None:
        kind = payload.get("kind", "tool_event")
        self._emit(kind, payload=payload)

    def events(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {"event_id": e.event_id, "plan_id": e.plan_id, "kind": e.kind,
                 "step_id": e.step_id, "payload": e.payload, "ts": e.ts}
                for e in self._events
            ]

    # ── Public entry ──

    def run(self, plan: Plan, *, context: Optional[Dict[str, Any]] = None) -> Plan:
        """Execute a pre-built Plan through the 6-node loop."""
        state = OrchestratorState(plan=plan)
        ctx: Dict[str, Any] = dict(context or {})
        ctx.setdefault("plan_id", plan.plan_id)
        ctx.setdefault("user_open_id", plan.user_open_id)
        ctx.setdefault("step_results", state.step_results)
        for k, v in (plan.meta or {}).items():
            ctx.setdefault(k, v)

        self._gather(state, ctx)
        while not state.finished:
            self._dispatch(state, ctx)
            self._verify(state, ctx)
            self._reflect(state, ctx)
        self._finish(state, ctx)
        return plan

    # ── Node 1: gather_context ──

    def _gather(self, state: OrchestratorState, ctx: Dict[str, Any]) -> None:
        plan = state.plan
        self._emit("plan_started", plan_id=plan.plan_id, payload={
            "intent": plan.intent, "total_steps": len(plan.steps),
            "mode": self._perm.mode.value,
        })

        # Fire SessionStart hook (inject LARKMENTOR.md etc.).
        sess_payload = self._hooks.fire(HookEvent.SESSION_START, {
            "project_root": ctx.get("project_root") or ".",
            "plan_id": plan.plan_id,
            "user_open_id": plan.user_open_id,
        })
        memory_injected = sess_payload.payload.get("memory_injected") or ""
        if memory_injected:
            state.messages.append({"role": "system",
                                    "content": "[LARKMENTOR.md]\n\n" + memory_injected})

        # Skills metadata (always in system prompt).
        try:
            skills_block = self._skills.metadata_block()
            if skills_block:
                state.messages.append({"role": "system", "content": skills_block})
        except Exception as exc:
            logger.debug("skills block skipped: %s", exc)

        # Memory recall (semantic).
        try:
            mems = self._mem.recall(plan.intent, user_id=plan.user_open_id or "default", k=5)
            if mems:
                lines = ["## 长期记忆召回（Mem0g / FlowMemory）", ""]
                for m in mems:
                    lines.append(f"- [{m.scope}] {m.content[:160]}")
                state.messages.append({"role": "system", "content": "\n".join(lines)})
        except Exception as exc:
            logger.debug("memory recall skipped: %s", exc)

        # UserPromptSubmit hook (classifier / sanitisation).
        up_payload = self._hooks.fire(HookEvent.USER_PROMPT_SUBMIT, {
            "intent": plan.intent,
            "plan_id": plan.plan_id,
            "user_open_id": plan.user_open_id,
        })
        if up_payload.vetoed:
            state.verdict = "failed"
            state.summary = f"user prompt vetoed: {up_payload.veto_reason}"
            state.finished = True
            self._emit("plan_vetoed", plan_id=plan.plan_id,
                       payload={"reason": up_payload.veto_reason})
            return

        state.messages.append({"role": "user", "content": plan.intent})

    # ── Node 2: plan (we use the provided Plan; replanning produces new steps) ──

    def _replan(self, state: OrchestratorState, ctx: Dict[str, Any]) -> None:
        """Produce new pending steps based on failures so far."""
        state.replans += 1
        self._emit("replan_started", plan_id=state.plan.plan_id,
                   payload={"replans": state.replans})

        # Strategy: mark failed steps as retry, or if a critical tool bug, ask user.
        retryable = [s for s in state.plan.steps if s.status == "failed" and s.tool not in ("im.send", "drive.delete")]
        if state.replans >= state.max_replans or not retryable:
            # Escalate: append a mentor.clarify step so the user decides.
            if self._tools.has("mentor.clarify"):
                new_step = PlanStep(
                    step_id=f"s_reask_{len(state.plan.steps)+1}",
                    tool="mentor.clarify",
                    description="连续失败 → 主动问用户",
                    args={"intent": state.plan.intent,
                          "questions": [
                              "刚才的计划部分失败，希望我重试还是换条路？",
                              "是否需要简化需求范围？"]},
                )
                state.plan.steps.append(new_step)
            return

        # Reset failed steps to pending for retry.
        for s in retryable[:2]:
            s.status = "pending"
            s.error = ""
            s.result = {}

    # ── Node 3: dispatch_tools ──

    def _dispatch(self, state: OrchestratorState, ctx: Dict[str, Any]) -> None:
        plan = state.plan
        ready = plan.ready_steps()
        if not ready:
            return

        # Resolve args + permission checks, build ToolInvocation list.
        invocations: List[ToolInvocation] = []
        skipped: List[PlanStep] = []
        for step in ready:
            args = _resolve_args(step.args or {}, state.step_results)

            # PreToolUse hook (may rewrite args or veto).
            hook_payload = self._hooks.fire(HookEvent.PRE_TOOL_USE, {
                "tool": step.tool, "args": args,
                "plan_id": plan.plan_id, "step_id": step.step_id,
                "user_open_id": plan.user_open_id,
                "permission_mode": self._perm.mode.value,
            })
            if hook_payload.vetoed:
                step.status = "failed"
                step.error = f"hook veto: {hook_payload.veto_reason}"
                self._emit("step_failed", plan_id=plan.plan_id, step_id=step.step_id,
                           payload={"error": step.error})
                skipped.append(step)
                continue

            args = hook_payload.payload.get("args") or args
            spec = self._tools.get(step.tool)
            readonly = bool(spec and spec.readonly)
            destructive = bool(spec and spec.destructive)

            # PermissionGate.
            perm = self._perm.check(
                tool=step.tool, readonly=readonly, destructive=destructive,
                user_open_id=plan.user_open_id, args=args,
            )
            if perm.is_denied():
                step.status = "failed"
                step.error = perm.to_llm_error()
                self._emit("step_failed", plan_id=plan.plan_id, step_id=step.step_id,
                           payload={"error": step.error, "permission_decision": perm.decision.value})
                skipped.append(step)
                continue
            if perm.needs_user_confirm() and ctx.get("auto_confirm") is not True:
                step.status = "failed"
                step.error = f"needs user confirm: {perm.reason}"
                self._emit("step_needs_confirm", plan_id=plan.plan_id, step_id=step.step_id,
                           payload={"reason": perm.reason, "tool": step.tool, "args_keys": list(args.keys())})
                skipped.append(step)
                continue

            # Build invocation.
            inv_ctx = dict(ctx)
            inv_ctx["step_id"] = step.step_id
            inv_ctx["tool"] = step.tool
            inv_ctx["description"] = step.description
            inv_ctx["step_results"] = state.step_results
            invocations.append(ToolInvocation(
                call_id=step.step_id, tool=step.tool, args=args, ctx=inv_ctx,
            ))
            step.status = "running"
            step.started_ts = int(time.time())
            self._emit("step_started", plan_id=plan.plan_id, step_id=step.step_id, payload={
                "tool": step.tool, "description": step.description,
            })

        if not invocations:
            return

        outcomes = self._executor.dispatch(invocations)

        # Apply outcomes back to plan.
        for outcome in outcomes:
            step = plan.find_step(outcome.call_id)
            if not step:
                continue
            step.finished_ts = int(time.time())
            if outcome.ok:
                step.status = "done"
                step.result = outcome.result or {}
                state.step_results[step.step_id] = step.result
                self._emit("step_done", plan_id=plan.plan_id, step_id=step.step_id, payload={
                    "tool": step.tool, "result": step.result,
                    "duration_ms": outcome.duration_ms,
                })
            else:
                step.status = "failed"
                step.error = outcome.error
                step.result = outcome.result or {}
                state.step_results[step.step_id] = {"error": outcome.error}
                self._emit("step_failed", plan_id=plan.plan_id, step_id=step.step_id, payload={
                    "tool": step.tool, "error": outcome.error,
                })
            # PostToolUse hook.
            self._hooks.fire(HookEvent.POST_TOOL_USE, {
                "tool": step.tool, "ok": outcome.ok,
                "result": step.result, "plan_id": plan.plan_id,
                "step_id": step.step_id, "user_open_id": plan.user_open_id,
            })

    # ── Node 4: verify ──

    def _verify(self, state: OrchestratorState, ctx: Dict[str, Any]) -> None:
        """Concrete-rule checks. Mark state.verdict."""
        plan = state.plan
        pending = [s for s in plan.steps if s.status == "pending"]
        failed = [s for s in plan.steps if s.status == "failed"]
        done = [s for s in plan.steps if s.status == "done"]

        if pending:
            state.verdict = "in_progress"
            return
        if failed:
            state.verdict = "partial" if done else "failed"
            return
        state.verdict = "ok"

    # ── Node 5: reflect ──

    def _reflect(self, state: OrchestratorState, ctx: Dict[str, Any]) -> None:
        """Classify current verdict and decide next action."""
        plan = state.plan
        if state.verdict == "in_progress":
            # More work scheduled; loop back without replan.
            if not plan.ready_steps():
                # Deadlock; bail.
                state.verdict = "failed"
                state.finished = True
            return
        if state.verdict == "ok":
            state.finished = True
            return
        # Partial or failed → try replan.
        if state.replans < state.max_replans:
            self._replan(state, ctx)
            # Re-evaluate ready after replan; if still nothing, finish.
            if not plan.ready_steps():
                state.finished = True
        else:
            state.finished = True

    # ── Node 6: finish ──

    def _finish(self, state: OrchestratorState, ctx: Dict[str, Any]) -> None:
        plan = state.plan
        stop_payload = self._hooks.fire(HookEvent.STOP, {
            "plan_id": plan.plan_id, "verdict": state.verdict,
            "user_open_id": plan.user_open_id,
        })
        done = sum(1 for s in plan.steps if s.status == "done")
        failed = sum(1 for s in plan.steps if s.status == "failed")
        summary = (
            f"verdict={state.verdict} done={done}/{len(plan.steps)} failed={failed} "
            f"replans={state.replans}"
        )
        state.summary = summary

        # Persist memory fact (last run summary).
        try:
            self._mem.remember(
                f"Plan {plan.plan_id}: {plan.intent[:80]} → {summary}",
                user_id=plan.user_open_id or "default",
                scope="session",
                tags=["agent-pilot", "run-summary"],
            )
        except Exception:
            pass

        self._emit("plan_done", plan_id=plan.plan_id, payload={
            "verdict": state.verdict, "done": done, "failed": failed,
            "replans": state.replans, "summary": summary,
        })

    # ── Accessors ──

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    @property
    def hooks(self) -> HookRegistry:
        return self._hooks

    @property
    def permissions(self) -> PermissionGate:
        return self._perm

    @property
    def memory(self) -> MemoryLayer:
        return self._mem

    @property
    def skills(self) -> SkillsLoader:
        return self._skills

    @property
    def context_manager(self) -> ContextManager:
        return self._ctxm


def _resolve_args(args: Dict[str, Any], step_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Placeholder expansion (same semantics as legacy orchestrator but stricter).

    Supports nested dot access and two syntaxes:
        ${s1.doc_token}
        {{s1.result.doc_token}}
    Unresolved placeholders become empty string (NOT the literal token) to
    avoid poisoning downstream tools with `{{..}}` leftovers.
    """
    import re
    placeholder_re = re.compile(r"\$\{([^}]+)\}|\{\{([^}]+)\}\}")

    def _lookup(token: str) -> Any:
        token = re.sub(r"\.result\.", ".", token.strip())
        parts = token.split(".")
        if not parts:
            return None
        step_id, rest = parts[0], parts[1:]
        cur: Any = step_results.get(step_id, {})
        for p in rest:
            if isinstance(cur, dict):
                cur = cur.get(p)
            else:
                return None
            if cur is None:
                return None
        return cur

    def _expand(v: Any) -> Any:
        if isinstance(v, str):
            # Whole-string placeholder: return resolved value (keeps type).
            m = placeholder_re.fullmatch(v.strip())
            if m:
                token = m.group(1) or m.group(2) or ""
                resolved = _lookup(token)
                return resolved if resolved is not None else ""
            # Embedded: do text replacement.
            def _sub(mm):
                token = mm.group(1) or mm.group(2) or ""
                resolved = _lookup(token)
                return str(resolved) if resolved is not None else ""
            return placeholder_re.sub(_sub, v)
        if isinstance(v, list):
            return [_expand(x) for x in v]
        if isinstance(v, dict):
            return {k: _expand(x) for k, x in v.items()}
        return v

    return {k: _expand(v) for k, v in args.items()}


_default: Optional[ConversationOrchestrator] = None
_default_lock = threading.Lock()


def default_orchestrator() -> ConversationOrchestrator:
    global _default
    with _default_lock:
        if _default is None:
            _default = ConversationOrchestrator()
            try:
                from core.sync.crdt_hub import attach_orchestrator
                attach_orchestrator(_default)
            except Exception as exc:
                logger.debug("crdt attach skipped: %s", exc)
        return _default
