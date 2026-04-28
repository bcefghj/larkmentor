"""Subagent Runner · Sidechain transcript (Claude Code 风格)

关键特性：
- 独立 context window（父 context 被保护）
- 只回传 summary（delta summarization）
- 禁止递归派生（max_depth=1）
- 并行执行支持
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("agent.subagent")


@dataclass
class SubagentResult:
    agent_id: str
    agent_type: str
    status: str  # "ok" / "failed" / "timeout"
    summary: str
    duration_ms: int
    tool_calls: int = 0
    tokens_used: int = 0
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubagentSpec:
    agent_type: str  # e.g. "researcher" / "writer" / "critic"
    task: str
    instruction: str = ""
    model: str = ""  # if empty, use routing default
    tools: List[str] = field(default_factory=list)  # tool allowlist
    max_turns: int = 5
    timeout_sec: int = 120
    parent_agent_id: Optional[str] = None


class SubagentRunner:
    def __init__(self, *, max_concurrent: int = 5, max_depth: int = 1) -> None:
        self.max_concurrent = max_concurrent
        self.max_depth = max_depth
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def spawn(
        self, spec: SubagentSpec, *,
        executor: Optional[Callable[[SubagentSpec], Dict[str, Any]]] = None,
        depth: int = 0,
    ) -> SubagentResult:
        """Spawn a single subagent. Returns summary-only result."""
        if depth >= self.max_depth:
            return SubagentResult(
                agent_id=str(uuid.uuid4())[:8],
                agent_type=spec.agent_type,
                status="failed",
                summary="",
                duration_ms=0,
                errors=["recursive subagent spawn blocked"],
            )

        async with self._semaphore:
            start = time.time()
            agent_id = f"{spec.agent_type}-{uuid.uuid4().hex[:6]}"
            try:
                if executor is None:
                    executor = self._default_executor
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, executor, spec),
                    timeout=spec.timeout_sec,
                )
                duration = int((time.time() - start) * 1000)
                summary = (result.get("summary", "") or str(result)[:2000])[:3000]
                return SubagentResult(
                    agent_id=agent_id,
                    agent_type=spec.agent_type,
                    status="ok",
                    summary=summary,
                    duration_ms=duration,
                    tool_calls=result.get("tool_calls", 0),
                    tokens_used=result.get("tokens_used", 0),
                    metadata=result.get("metadata", {}),
                )
            except asyncio.TimeoutError:
                duration = int((time.time() - start) * 1000)
                return SubagentResult(
                    agent_id=agent_id, agent_type=spec.agent_type,
                    status="timeout", summary="", duration_ms=duration,
                    errors=[f"timed out after {spec.timeout_sec}s"],
                )
            except Exception as e:
                duration = int((time.time() - start) * 1000)
                logger.exception("subagent %s failed", agent_id)
                return SubagentResult(
                    agent_id=agent_id, agent_type=spec.agent_type,
                    status="failed", summary="", duration_ms=duration,
                    errors=[str(e)[:500]],
                )

    async def spawn_parallel(
        self, specs: List[SubagentSpec], *,
        executor: Optional[Callable] = None,
    ) -> List[SubagentResult]:
        """Fan-out pattern: spawn N subagents in parallel, collect all."""
        tasks = [self.spawn(s, executor=executor) for s in specs]
        return await asyncio.gather(*tasks)

    async def spawn_pipeline(
        self, stages: List[List[SubagentSpec]], *,
        executor: Optional[Callable] = None,
    ) -> List[List[SubagentResult]]:
        """Pipeline pattern: stage i runs in parallel, stage i+1 waits on i."""
        all_results = []
        for stage in stages:
            results = await self.spawn_parallel(stage, executor=executor)
            all_results.append(results)
        return all_results

    def _default_executor(self, spec: SubagentSpec) -> Dict[str, Any]:
        """Default: invoke LLM with minimal system prompt + task."""
        try:
            from llm.llm_client import chat as llm_chat
            system = spec.instruction or f"You are a specialist subagent: {spec.agent_type}. Return a concise summary."
            user = spec.task
            resp = llm_chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.4,
                max_tokens=1200,
            )
            return {"summary": resp, "tool_calls": 0, "tokens_used": len(resp) // 4}
        except Exception as e:
            return {"summary": "", "metadata": {"error": str(e)}}

    def sync_spawn(self, spec: SubagentSpec) -> SubagentResult:
        """Synchronous wrapper for non-async callers."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError("use spawn() in async context")
            return loop.run_until_complete(self.spawn(spec))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self.spawn(spec))
            finally:
                loop.close()

    def sync_spawn_parallel(self, specs: List[SubagentSpec]) -> List[SubagentResult]:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.spawn_parallel(specs))
        finally:
            loop.close()


_singleton: Optional[SubagentRunner] = None


def default_subagent_runner() -> SubagentRunner:
    global _singleton
    if _singleton is None:
        _singleton = SubagentRunner()
    return _singleton
