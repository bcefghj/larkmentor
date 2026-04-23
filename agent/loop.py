"""Agent Loop · 9 步 pipeline（对齐 Claude Code queryLoop）

9 步骤（参考 arxiv:2604.14228 §4.3）：
1. Settings resolution
2. State init
3. Context assembly
4. 5 层压缩
5. Model call
6. Tool dispatch
7. Permission gate
8. Tool execution
9. Stop condition
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .context import default_context_manager, ContextManager
from .permissions import default_permission_gate, PermissionGate, Decision
from .hooks import default_hook_registry, HookRegistry, HookEvent
from .memory import default_memory, MemoryLayer
from .skills import default_skills_loader, SkillsLoader
from .mcp import default_mcp_manager, MCPManager
from .subagent import default_subagent_runner, SubagentRunner

logger = logging.getLogger("agent.loop")


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
    name: str  # one of the 9 step names
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
    """Core Claude Code-style agent loop."""

    def __init__(
        self, *,
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
        self.tool_registry: Dict[str, Callable] = {}
        self.step_listeners: List[Callable[[LoopStep], None]] = []

    def register_tool(self, name: str, fn: Callable) -> None:
        self.tool_registry[name] = fn
        logger.debug("tool registered: %s", name)

    def on_step(self, fn: Callable[[LoopStep], None]) -> None:
        self.step_listeners.append(fn)

    def _emit(self, step: LoopStep) -> None:
        for fn in self.step_listeners:
            try:
                fn(step)
            except Exception:
                pass

    # ── Main loop ──────────────────────────

    def run(
        self, prompt: str, *,
        user_open_id: str = "",
        tenant_id: str = "default",
        session_id: Optional[str] = None,
        max_turns: int = 6,
        context: Optional[Dict[str, Any]] = None,
    ) -> LoopResult:
        session_id = session_id or f"sess-{uuid.uuid4().hex[:8]}"
        steps: List[LoopStep] = []
        tool_calls: List[ToolCall] = []
        messages: List[Dict[str, Any]] = []
        final_text = ""
        context = context or {}

        # ── Step 1: Settings resolution ──
        t = time.time()
        step = LoopStep(index=1, name="settings_resolution")
        settings = self._resolve_settings()
        step.status = "ok"; step.duration_ms = int((time.time() - t) * 1000)
        step.detail = {"providers": list(settings.get("providers", {}).keys())}
        steps.append(step); self._emit(step)

        # ── Step 2: State init ──
        t = time.time()
        step = LoopStep(index=2, name="state_init")
        hook_out = self.hooks.fire(HookEvent.SESSION_START, {
            "session_id": session_id, "user_open_id": user_open_id,
            "tenant_id": tenant_id, "prompt": prompt,
        })
        system_prompt_parts = []
        if hook_out.payload.get("system_prompt"):
            system_prompt_parts.append(hook_out.payload["system_prompt"])
        if self.skills.l1_system_prompt():
            system_prompt_parts.append(self.skills.l1_system_prompt())
        if system_prompt_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_prompt_parts)})
        step.status = "ok"; step.duration_ms = int((time.time() - t) * 1000)
        step.detail = {"session_id": session_id, "sys_prompt_chars": sum(len(p) for p in system_prompt_parts)}
        steps.append(step); self._emit(step)

        # ── Step 3: Context assembly ──
        t = time.time()
        step = LoopStep(index=3, name="context_assembly")
        recent = self.memory.recent(tenant_id=tenant_id, limit=5)
        if recent:
            recall_lines = [f"- [{e.kind}] {e.content[:120]}" for e in recent]
            messages.append({"role": "system", "content": "=== RECENT MEMORY RECALL ===\n" + "\n".join(recall_lines)})
        hook_up = self.hooks.fire(HookEvent.USER_PROMPT_SUBMIT, {
            "session_id": session_id, "prompt": prompt, "user_open_id": user_open_id,
        })
        if hook_up.vetoed:
            return LoopResult(session_id=session_id, final_text="",
                              tool_calls=[], steps=steps, status="vetoed",
                              error=hook_up.veto_reason)
        messages.append({"role": "user", "content": prompt})
        step.status = "ok"; step.duration_ms = int((time.time() - t) * 1000)
        step.detail = {"msg_count": len(messages), "recall_count": len(recent)}
        steps.append(step); self._emit(step)

        # ── Multi-turn loop ──
        turn = 0
        while turn < max_turns:
            turn += 1

            # ── Step 4: Compaction ──
            t = time.time()
            step = LoopStep(index=4, name=f"compaction_turn{turn}")
            messages, events = self.context_manager.shape(messages)
            step.status = "ok"; step.duration_ms = int((time.time() - t) * 1000)
            step.detail = {
                "msg_count": len(messages),
                "events": [{"layer": e.layer, "ratio": e.ratio()} for e in events],
            }
            steps.append(step); self._emit(step)

            # ── Step 5: Model call ──
            t = time.time()
            step = LoopStep(index=5, name=f"model_call_turn{turn}")
            model_output = self._call_llm(messages, context=context)
            step.status = "ok" if model_output else "failed"
            step.duration_ms = int((time.time() - t) * 1000)
            step.detail = {"chars": len(model_output) if model_output else 0}
            steps.append(step); self._emit(step)

            if not model_output:
                break

            # Parse tool calls from model output
            parsed_tools = self._parse_tool_calls(model_output)

            # If no tools → final answer
            if not parsed_tools:
                final_text = model_output
                messages.append({"role": "assistant", "content": model_output})
                break

            messages.append({"role": "assistant", "content": model_output})

            # ── Step 6-8: Tool dispatch → Permission gate → Tool execution ──
            for tcall in parsed_tools:
                t = time.time()
                step = LoopStep(index=6, name=f"tool_{tcall.name}_turn{turn}")

                # Step 7: Permission gate
                dec = self.permissions.check(tcall.name, tcall.arguments)
                if dec.decision == Decision.DENY:
                    tcall.error = f"denied by {dec.layer}: {dec.reason or dec.matched_rule or ''}"
                    step.status = "denied"; step.duration_ms = int((time.time() - t) * 1000)
                    step.detail = {"tool": tcall.name, "layer": dec.layer, "reason": tcall.error}
                    steps.append(step); self._emit(step)
                    tool_calls.append(tcall)
                    messages.append({
                        "role": "tool", "name": tcall.name,
                        "content": f"PERMISSION_DENIED: {tcall.error}"
                    })
                    continue
                if dec.decision == Decision.ASK:
                    # Surface ask-decision via tool message; LLM may rephrase
                    tcall.error = f"ask_required: {dec.layer}"
                    step.status = "asked"; step.duration_ms = int((time.time() - t) * 1000)
                    step.detail = {"tool": tcall.name, "layer": dec.layer}
                    steps.append(step); self._emit(step)
                    tool_calls.append(tcall)
                    messages.append({
                        "role": "tool", "name": tcall.name,
                        "content": f"PERMISSION_ASK_REQUIRED: {dec.layer} — please request explicit approval from user."
                    })
                    continue

                # Pre-tool hook
                pre = self.hooks.fire(HookEvent.PRE_TOOL_USE, {
                    "session_id": session_id, "tool": tcall.name,
                    "arguments": tcall.arguments, "user_open_id": user_open_id,
                    "plan_id": context.get("plan_id", ""),
                })
                if pre.vetoed:
                    tcall.error = f"pre_tool_veto: {pre.veto_reason}"
                    step.status = "vetoed"; step.duration_ms = int((time.time() - t) * 1000)
                    steps.append(step); self._emit(step)
                    tool_calls.append(tcall)
                    messages.append({"role": "tool", "name": tcall.name, "content": f"VETOED: {pre.veto_reason}"})
                    continue

                # Step 8: execute
                try:
                    fn = self.tool_registry.get(tcall.name)
                    if fn:
                        tcall.result = fn(**tcall.arguments)
                    else:
                        # try MCP
                        for alias in self.mcp.clients:
                            res = self.mcp.call(alias, tcall.name, tcall.arguments)
                            if res:
                                tcall.result = res
                                break
                        else:
                            tcall.error = f"tool_not_found: {tcall.name}"
                    self.permissions.on_allowed()
                except Exception as e:
                    tcall.error = f"exec_failed: {e}"
                    logger.exception("tool %s failed", tcall.name)

                tcall.duration_ms = int((time.time() - t) * 1000)
                step.status = "ok" if not tcall.error else "failed"
                step.duration_ms = tcall.duration_ms
                step.detail = {"tool": tcall.name, "error": tcall.error}
                steps.append(step); self._emit(step)
                tool_calls.append(tcall)

                # Post-tool hook
                self.hooks.fire(HookEvent.POST_TOOL_USE, {
                    "session_id": session_id, "tool": tcall.name,
                    "arguments": tcall.arguments, "result": tcall.result,
                    "ok": not tcall.error, "plan_id": context.get("plan_id", ""),
                    "user_open_id": user_open_id,
                })

                messages.append({
                    "role": "tool", "name": tcall.name,
                    "content": json.dumps(tcall.result, ensure_ascii=False, default=str)[:8000] if tcall.result else (tcall.error or ""),
                })

            # ── Step 9: stop condition ──
            step = LoopStep(index=9, name=f"stop_check_turn{turn}")
            step.detail = {"turn": turn, "has_errors": any(tc.error for tc in tool_calls[-len(parsed_tools):])}
            steps.append(step); self._emit(step)

        # Final stop hook
        stop_hook = self.hooks.fire(HookEvent.STOP, {
            "session_id": session_id, "final_text": final_text,
            "tool_calls_count": len(tool_calls), "user_open_id": user_open_id,
        })
        if stop_hook.payload.get("final_text"):
            final_text = stop_hook.payload["final_text"]

        # Persist session summary to memory
        try:
            self.memory.upsert(
                content=f"User asked: {prompt[:200]}\nAgent answered: {final_text[:300]}",
                kind="session_summary", user_id=user_open_id,
                session_id=session_id, tenant_id=tenant_id,
            )
        except Exception:
            pass

        return LoopResult(
            session_id=session_id, final_text=final_text,
            tool_calls=tool_calls, steps=steps,
            status="ok" if final_text or any(not tc.error for tc in tool_calls) else "failed",
        )

    # ── Helpers ──────────────────────────

    def _resolve_settings(self) -> Dict[str, Any]:
        try:
            from .providers import default_providers
            return {"providers": default_providers().snapshot()}
        except Exception:
            return {"providers": {}}

    def _call_llm(self, messages: List[Dict], *, context: Dict[str, Any]) -> str:
        try:
            from .providers import default_providers
            providers = default_providers()
            task_kind = context.get("task_kind", "chinese_chat")
            return providers.chat(messages, task_kind=task_kind)
        except Exception as e:
            logger.warning("providers.chat failed, falling back to llm_client: %s", e)
            try:
                from llm.llm_client import chat as _chat
                return _chat(messages=messages, temperature=0.4, max_tokens=1200)
            except Exception as e2:
                logger.error("LLM call failed: %s", e2)
                return ""

    def _parse_tool_calls(self, text: str) -> List[ToolCall]:
        """Parse tool calls from LLM output.

        Supported formats:
        1. JSON block: ```tool_call\\n{"name": ..., "arguments": ...}\\n```
        2. XML-like: <tool_call>{"name": ..., "arguments": ...}</tool_call>
        3. Multiple per response
        """
        import re
        calls: List[ToolCall] = []

        # Fence code pattern
        for m in re.finditer(r"```tool_call\s*\n(.*?)\n```", text, re.DOTALL):
            try:
                data = json.loads(m.group(1))
                calls.append(ToolCall(name=data.get("name", ""), arguments=data.get("arguments", {})))
            except Exception:
                continue

        # XML tag pattern
        for m in re.finditer(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL):
            try:
                data = json.loads(m.group(1))
                calls.append(ToolCall(name=data.get("name", ""), arguments=data.get("arguments", {})))
            except Exception:
                continue

        return calls


_singleton: Optional[AgentLoop] = None


def default_loop() -> AgentLoop:
    global _singleton
    if _singleton is None:
        _singleton = AgentLoop()
    return _singleton
