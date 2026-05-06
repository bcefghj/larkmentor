"""8 步 Claude Code Harness Loop — V1 编排核心.

严格按 Sid Bharath「The Anatomy of Claude Code」反推的内部循环重构:

    1. Assemble Context  → system prompt + AGENTS.md cascade + memory + history
    2. Call LLM API     → streaming via async generator
    3. Parse Response   → text blocks + tool_use blocks
    4. Check Permission → deny → allow → classifier → ask user
    5. Execute Tools    → read-only parallel, write serial（Cognition 教训）
    6. Feed Results Back → tool results 变成 message
    7. Context Check    → 超长则 compact / reset
    8. Termination      → 无 tool_use 则结束

设计原则:
  - Runtime 层不直接调 LLM、不直接读写飞书；通过 Capability/Governance 接口委托
  - 缓存稳定（cache stability first）：system prompt 用 SYSTEM_PROMPT_DYNAMIC_BOUNDARY 切两段
  - filesystem as working memory：大段内容落盘后用 ArtifactRef 引用
  - 单线程写：`Cognition`原则——多个 read 工具可并行，write 必须串行
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Protocol

from pilot.runtime.session import (
    Artifact,
    Session,
    Step,
    StepKind,
    StepStatus,
    Task,
)

logger = logging.getLogger("pilot.runtime.harness")


# ── Protocols（5 层架构边界）─────────────────────────────────────────────────


class LLMClient(Protocol):
    """Capability 层注入的 LLM 客户端."""

    async def chat_stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.5,
    ) -> AsyncIterator[dict[str, Any]]:
        ...

    async def chat(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.5,
    ) -> dict[str, Any]:
        ...


class ToolDispatcher(Protocol):
    """Capability 层注入的工具执行器."""

    def is_read_only(self, tool_name: str) -> bool:
        ...

    async def execute(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class ContextAssembler(Protocol):
    """Context 层注入的 prompt 组装器."""

    async def assemble_system_prompt(self, session: Session) -> str:
        ...

    async def assemble_messages(self, session: Session, task: Task | None) -> list[dict[str, Any]]:
        ...

    async def append_event(self, session: Session, kind: str, payload: dict[str, Any]) -> None:
        ...

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        ...


class PermissionGate(Protocol):
    """Governance 层注入的权限策略."""

    async def check(
        self,
        *,
        session: Session,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> "PermissionDecision":
        ...


@dataclass
class PermissionDecision:
    verdict: str  # "allow" | "deny" | "ask"
    reason: str = ""
    require_human: bool = False


@dataclass
class HarnessEvent:
    """Harness 单步事件——可被 broadcaster 转发到 Surface 层 (Dashboard / 飞书卡片)."""

    kind: str
    step_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


EventCallback = Callable[[HarnessEvent], Awaitable[None]]


# ── 主循环 ──────────────────────────────────────────────────────────────────


@dataclass
class HarnessConfig:
    max_turns: int = 20
    context_reset_threshold_tokens: int = 120_000
    parallel_read_tools: bool = True
    enable_streaming: bool = True


class HarnessLoop:
    """Claude Code 8 步 harness loop 的标准实现.

    用法:

        harness = HarnessLoop(llm=..., tools=..., context=..., perm=...)
        async for event in harness.run(session, task):
            print(event.kind, event.payload)
    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        tools: ToolDispatcher,
        context: ContextAssembler,
        perm: PermissionGate,
        config: HarnessConfig | None = None,
        on_event: EventCallback | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.context = context
        self.perm = perm
        self.config = config or HarnessConfig()
        self.on_event = on_event
        self._steps: list[Step] = []

    # ── 主循环 ──
    async def run(
        self,
        session: Session,
        task: Task | None,
        *,
        user_message: str = "",
        available_tool_schemas: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        """运行 8 步 harness loop，逐 turn 流出 HarnessEvent."""
        await self._emit(HarnessEvent(kind="harness.start", payload={
            "session_id": session.session_id,
            "task_id": task.task_id if task else "",
            "user_message": user_message[:200],
        }))

        turns = 0
        last_reason = "max_turns"
        try:
            while turns < self.config.max_turns:
                turns += 1
                logger.debug("harness turn %d", turns)

                # Step 1: Assemble Context
                async for ev in self._step_assemble(session, task, user_message if turns == 1 else ""):
                    yield ev

                # Step 2: Call LLM API
                llm_result = None
                async for ev, result in self._step_call_llm(session, task, available_tool_schemas or []):
                    yield ev
                    if result is not None:
                        llm_result = result
                if not llm_result:
                    last_reason = "llm_call_failed"
                    break

                # Step 3: Parse Response
                text_blocks, tool_calls = self._step_parse(llm_result)
                yield HarnessEvent(kind="harness.parse", payload={
                    "text_len": sum(len(t) for t in text_blocks),
                    "tool_calls": [tc.get("name") for tc in tool_calls],
                })

                if text_blocks:
                    text_payload = "\n".join(text_blocks)
                    await self.context.append_event(session, "assistant_text", {"text": text_payload})

                # Step 8 提前判断: 没工具调用 = 终止
                if not tool_calls:
                    last_reason = "natural_termination"
                    break

                # Step 4 + 5: 权限检查 + 执行（read 并行 / write 串行）
                tool_results = []
                async for ev, results in self._step_permit_and_execute(session, task, tool_calls):
                    yield ev
                    if results is not None:
                        tool_results.extend(results)

                # Step 6: Feed Results Back
                for tr in tool_results:
                    await self.context.append_event(session, "tool_result", tr)
                yield HarnessEvent(kind="harness.feedback", payload={"count": len(tool_results)})

                # Step 7: Context Check
                msgs = await self.context.assemble_messages(session, task)
                tokens = self.context.estimate_tokens(msgs)
                session.context_state["tokens_used"] = tokens
                if tokens >= self.config.context_reset_threshold_tokens:
                    yield HarnessEvent(kind="harness.context_reset", payload={"tokens": tokens})
                    await self.context.append_event(session, "context_reset", {"tokens": tokens})
                    session.context_state["compacted"] = True

            else:
                last_reason = "max_turns_exhausted"

        except Exception as e:
            logger.exception("harness loop error: %s", e)
            yield HarnessEvent(kind="harness.error", payload={"error": str(e)})
            last_reason = "exception"
        finally:
            yield HarnessEvent(kind="harness.end", payload={
                "turns": turns,
                "reason": last_reason,
                "tokens": session.context_state.get("tokens_used", 0),
            })
            await self._emit(HarnessEvent(kind="harness.end", payload={
                "session_id": session.session_id,
                "turns": turns,
                "reason": last_reason,
            }))

    # ── Step 1: Assemble Context ──
    async def _step_assemble(
        self,
        session: Session,
        task: Task | None,
        new_user_message: str,
    ) -> AsyncIterator[HarnessEvent]:
        if new_user_message:
            await self.context.append_event(session, "user_message", {"text": new_user_message})
        yield HarnessEvent(kind="harness.assemble", payload={
            "session_id": session.session_id,
        })

    # ── Step 2: Call LLM ──
    async def _step_call_llm(
        self,
        session: Session,
        task: Task | None,
        tool_schemas: list[dict[str, Any]],
    ) -> AsyncIterator[tuple[HarnessEvent, dict[str, Any] | None]]:
        system = await self.context.assemble_system_prompt(session)
        messages = await self.context.assemble_messages(session, task)

        step = Step(
            session_id=session.session_id,
            task_id=task.task_id if task else "",
            kind=StepKind.LLM_CALL,
            tool_name="",
        )
        step.start()
        self._steps.append(step)
        yield (HarnessEvent(kind="harness.llm_call.start", step_id=step.step_id, payload={
            "tools": [t.get("name") for t in tool_schemas],
        }), None)

        try:
            result = await self.llm.chat(
                system=system,
                messages=messages,
                tools=tool_schemas,
                temperature=0.5,
            )
            step.complete(output={"raw": result})
            yield (HarnessEvent(kind="harness.llm_call.done", step_id=step.step_id, payload={
                "duration_ms": step.duration_ms,
                "tokens_in": step.tokens_in,
                "tokens_out": step.tokens_out,
            }), result)
        except Exception as e:
            step.fail(str(e))
            yield (HarnessEvent(kind="harness.llm_call.error", step_id=step.step_id, payload={
                "error": str(e),
            }), None)

    # ── Step 3: Parse Response ──
    @staticmethod
    def _step_parse(llm_result: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
        """从 LLM 响应中拆出 text blocks 与 tool_use blocks.

        兼容 Anthropic / OpenAI / 自研 LLM 客户端三种返回格式。
        """
        text_blocks: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        # 格式 A: Anthropic content list
        content = llm_result.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type")
                    if btype == "text":
                        text_blocks.append(block.get("text", ""))
                    elif btype == "tool_use":
                        tool_calls.append({
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "input": block.get("input", {}),
                        })

        # 格式 B: OpenAI tool_calls
        if not tool_calls and "tool_calls" in llm_result:
            for tc in llm_result.get("tool_calls", []) or []:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"_raw": args}
                tool_calls.append({"id": tc.get("id", ""), "name": fn.get("name", ""), "input": args})

        # 格式 C: 简单文本
        if not text_blocks and isinstance(llm_result.get("text"), str):
            text_blocks.append(llm_result["text"])
        if not text_blocks and isinstance(content, str):
            text_blocks.append(content)

        return text_blocks, tool_calls

    # ── Step 4 + 5: Permit + Execute ──
    async def _step_permit_and_execute(
        self,
        session: Session,
        task: Task | None,
        tool_calls: list[dict[str, Any]],
    ) -> AsyncIterator[tuple[HarnessEvent, list[dict[str, Any]] | None]]:
        # 4. 权限分组
        approved: list[dict[str, Any]] = []
        denied: list[dict[str, Any]] = []
        for tc in tool_calls:
            decision = await self.perm.check(
                session=session,
                tool_name=tc.get("name", ""),
                tool_input=tc.get("input", {}),
            )
            if decision.verdict == "deny":
                denied.append({**tc, "_decision": decision.__dict__})
            else:
                approved.append(tc)
        yield (HarnessEvent(kind="harness.permit", payload={
            "approved": [a["name"] for a in approved],
            "denied": [d["name"] for d in denied],
        }), None)

        if denied:
            denial_msgs = [
                {"role": "tool", "tool_use_id": tc.get("id", ""), "content": f"PermissionDenied: {tc['_decision']['reason']}"}
                for tc in denied
            ]
            yield (HarnessEvent(kind="harness.tools.denied", payload={"items": denial_msgs}), denial_msgs)

        # 5. 分组执行：read-only 并行、write 串行
        read_only_calls = [tc for tc in approved if self.tools.is_read_only(tc.get("name", ""))]
        write_calls = [tc for tc in approved if not self.tools.is_read_only(tc.get("name", ""))]

        results: list[dict[str, Any]] = []

        # read 并行
        if read_only_calls:
            yield (HarnessEvent(kind="harness.tools.read.start", payload={
                "names": [tc["name"] for tc in read_only_calls],
            }), None)
            tasks = [self._exec_one(session, task, tc) for tc in read_only_calls]
            done = await asyncio.gather(*tasks, return_exceptions=True)
            for tc, r in zip(read_only_calls, done, strict=False):
                if isinstance(r, Exception):
                    results.append({
                        "role": "tool",
                        "tool_use_id": tc.get("id", ""),
                        "tool_name": tc["name"],
                        "content": f"ToolError: {r}",
                        "ok": False,
                    })
                else:
                    results.append(r)
            yield (HarnessEvent(kind="harness.tools.read.done", payload={"count": len(read_only_calls)}), None)

        # write 串行（Cognition 单线程写）
        for tc in write_calls:
            yield (HarnessEvent(kind="harness.tools.write.start", payload={"name": tc["name"]}), None)
            try:
                r = await self._exec_one(session, task, tc)
                results.append(r)
                yield (HarnessEvent(kind="harness.tools.write.done", payload={"name": tc["name"]}), None)
            except Exception as e:
                results.append({
                    "role": "tool",
                    "tool_use_id": tc.get("id", ""),
                    "tool_name": tc["name"],
                    "content": f"ToolError: {e}",
                    "ok": False,
                })
                yield (HarnessEvent(kind="harness.tools.write.error", payload={
                    "name": tc["name"],
                    "error": str(e),
                }), None)

        yield (HarnessEvent(kind="harness.tools.summary", payload={
            "total": len(approved),
            "denied": len(denied),
        }), results)

    async def _exec_one(self, session: Session, task: Task | None, tc: dict[str, Any]) -> dict[str, Any]:
        step = Step(
            session_id=session.session_id,
            task_id=task.task_id if task else "",
            kind=StepKind.TOOL_CALL,
            tool_name=tc.get("name", ""),
            input={"args": tc.get("input", {})},
        )
        step.start()
        self._steps.append(step)
        try:
            output = await self.tools.execute(
                tool_name=tc.get("name", ""),
                tool_input=tc.get("input", {}),
                ctx={"session": session, "task": task, "step_id": step.step_id},
            )
            step.complete(output=output)
            return {
                "role": "tool",
                "tool_use_id": tc.get("id", ""),
                "tool_name": tc["name"],
                "content": output,
                "ok": True,
                "step_id": step.step_id,
                "duration_ms": step.duration_ms,
            }
        except Exception as e:
            step.fail(str(e))
            raise

    async def _emit(self, ev: HarnessEvent) -> None:
        if self.on_event:
            try:
                await self.on_event(ev)
            except Exception as e:
                logger.debug("on_event handler failed: %s", e)

    @property
    def steps(self) -> list[Step]:
        return list(self._steps)
