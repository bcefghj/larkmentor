"""Agent Loop · thin adapter over ConversationOrchestrator.

The canonical execution engine is
``core.agent_pilot.harness.orchestrator_v2.ConversationOrchestrator``.
New code should use ``ConversationOrchestrator.run(plan)`` directly.

The public API (``ToolCall``, ``LoopStep``, ``LoopResult``, ``AgentLoop``,
``default_loop``) is preserved unchanged so that existing callers keep
working.  Internally ``AgentLoop.run()`` delegates to the orchestrator.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .context import ContextManager, default_context_manager
from .hooks import HookEvent, HookRegistry, default_hook_registry
from .mcp import MCPManager, default_mcp_manager
from .memory import MemoryLayer, default_memory
from .permissions import Decision, PermissionGate, default_permission_gate
from .skills import SkillsLoader, default_skills_loader
from .subagent import SubagentRunner, default_subagent_runner

logger = logging.getLogger("agent.loop")

# ── Import the orchestrator (required) ──

from core.agent_pilot.harness.orchestrator_v2 import ConversationOrchestrator
from core.agent_pilot.planner import Plan, PlanStep


# ── Public dataclasses (unchanged) ──


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: int = 0


@dataclass
class LoopStep:
    index: int
    name: str
    status: str = "pending"
    duration_ms: int = 0
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LoopResult:
    session_id: str
    final_text: str
    tool_calls: List[ToolCall]
    steps: List[LoopStep]
    status: str  # "ok" / "failed" / "stopped" / "vetoed"
    tokens_used: int = 0
    cost_cny: float = 0.0
    error: Optional[str] = None


class AgentLoop:
    """Core agent loop – delegates to ConversationOrchestrator."""

    def __init__(
        self,
        *,
        context_manager: Optional[ContextManager] = None,
        permissions: Optional[PermissionGate] = None,
        hooks: Optional[HookRegistry] = None,
        memory: Optional[MemoryLayer] = None,
        skills: Optional[SkillsLoader] = None,
        mcp: Optional[MCPManager] = None,
        subagent: Optional[SubagentRunner] = None,
    ) -> None:
        self.context_manager = context_manager or default_context_manager()
        self.permissions = permissions or default_permission_gate()
        self.hooks = hooks or default_hook_registry()
        self.memory = memory or default_memory()
        self.skills = skills or default_skills_loader()
        self.mcp = mcp or default_mcp_manager()
        self.subagent = subagent or default_subagent_runner()

    # ── Main entry point ──────────────────────────

    def run(
        self,
        prompt: str,
        *,
        user_open_id: str = "",
        tenant_id: str = "default",
        session_id: Optional[str] = None,
        max_turns: int = 6,
        context: Optional[Dict[str, Any]] = None,
    ) -> LoopResult:
        return self._orchestrated_run(
            prompt,
            user_open_id=user_open_id,
            tenant_id=tenant_id,
            session_id=session_id,
            max_turns=max_turns,
            context=context,
        )

    # ── Orchestrator-backed implementation ──────────────────────────

    def _orchestrated_run(
        self,
        prompt: str,
        *,
        user_open_id: str = "",
        tenant_id: str = "default",
        session_id: Optional[str] = None,
        max_turns: int = 6,
        context: Optional[Dict[str, Any]] = None,
    ) -> LoopResult:
        session_id = session_id or f"sess-{uuid.uuid4().hex[:8]}"
        context = context or {}

        steps: List[LoopStep] = []
        t0 = time.time()

        # Step 1 – Build a Plan from the prompt.
        step = LoopStep(index=1, name="build_plan")
        plan = self._build_plan(prompt, user_open_id=user_open_id, session_id=session_id)
        plan.meta.setdefault("tenant_id", tenant_id)
        plan.meta.setdefault("max_turns", max_turns)
        step.status = "ok"
        step.duration_ms = int((time.time() - t0) * 1000)
        step.detail = {"plan_id": plan.plan_id, "plan_steps": len(plan.steps)}
        steps.append(step)

        # Step 2 – Instantiate orchestrator and run.
        t1 = time.time()
        step = LoopStep(index=2, name="orchestrator_run")

        orchestrator = ConversationOrchestrator(
            hooks=self.hooks,
            permissions=self.permissions,
            memory=self.memory,
            skills=self.skills,
        )

        finished_plan = orchestrator.run(plan, context=context)

        step.status = "ok"
        step.duration_ms = int((time.time() - t1) * 1000)
        step.detail = {"verdict": _plan_verdict(finished_plan)}
        steps.append(step)

        # Step 3 – Convert orchestrator results → LoopResult.
        return self._plan_to_loop_result(
            finished_plan,
            session_id=session_id,
            steps=steps,
        )

    def _build_plan(
        self,
        prompt: str,
        *,
        user_open_id: str,
        session_id: str,
    ) -> Plan:
        """Try the PilotPlanner; fall back to a single-step 'chat' plan."""
        try:
            from core.agent_pilot.planner import plan_from_intent

            return plan_from_intent(prompt, user_open_id=user_open_id)
        except Exception:
            logger.debug("planner unavailable – building single-step plan")

        plan_id = f"plan_{session_id}"
        return Plan(
            plan_id=plan_id,
            user_open_id=user_open_id,
            intent=prompt,
            steps=[
                PlanStep(
                    step_id="s1",
                    tool="mentor.summarize",
                    description="直接回答用户",
                    args={"context": prompt},
                ),
            ],
            created_ts=int(time.time()),
            meta={},
        )

    @staticmethod
    def _plan_to_loop_result(
        plan: Plan,
        *,
        session_id: str,
        steps: List[LoopStep],
    ) -> LoopResult:
        tool_calls: List[ToolCall] = []
        final_text_parts: List[str] = []

        for ps in plan.steps:
            tc = ToolCall(
                name=ps.tool,
                arguments=ps.args or {},
                result=ps.result if ps.status == "done" else None,
                error=ps.error or None,
                duration_ms=((ps.finished_ts - ps.started_ts) * 1000 if ps.finished_ts and ps.started_ts else 0),
            )
            tool_calls.append(tc)

            if ps.status == "done" and ps.result:
                text = ps.result.get("text") or ps.result.get("summary") or ""
                if text:
                    final_text_parts.append(str(text))

            loop_step = LoopStep(
                index=len(steps) + 1,
                name=f"tool_{ps.tool}",
                status=ps.status,
                duration_ms=tc.duration_ms,
                detail={"step_id": ps.step_id, "tool": ps.tool, "error": ps.error},
            )
            steps.append(loop_step)

        verdict = _plan_verdict(plan)
        final_text = "\n\n".join(final_text_parts)

        return LoopResult(
            session_id=session_id,
            final_text=final_text,
            tool_calls=tool_calls,
            steps=steps,
            status=verdict,
        )


# ── Helpers (module-level) ──


def _plan_verdict(plan: Plan) -> str:
    """Derive an ok/partial/failed status string from a finished Plan."""
    done = sum(1 for s in plan.steps if s.status == "done")
    failed = sum(1 for s in plan.steps if s.status == "failed")
    if failed == 0 and done == len(plan.steps):
        return "ok"
    if done > 0:
        return "ok"
    return "failed"


# ── Singleton factory ──


_singleton: Optional[AgentLoop] = None


def default_loop() -> AgentLoop:
    global _singleton
    if _singleton is None:
        _singleton = AgentLoop()
    return _singleton
