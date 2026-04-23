"""Subagent runner (Claude Code `Task` / `Agent` tool).

Key properties
--------------
* **Isolated context**: a subagent does NOT see parent's transcript or
  tool results. It only gets its system prompt + the prompt string
  passed when spawning.
* **One-shot summary**: subagent returns a single final message
  (string + structured facts) to the parent. Parent never sees the
  subagent's intermediate steps, to keep main context clean.
* **No recursion**: subagents cannot spawn further subagents (we
  enforce this by removing the Task tool from the subagent's registry).
* **Parallelism**: multiple subagents can run concurrently via
  ThreadPoolExecutor.
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("pilot.harness.subagent")


@dataclass
class SubagentResult:
    subagent_id: str
    prompt: str
    summary: str
    facts: Dict[str, Any] = field(default_factory=dict)
    started_ts: int = 0
    finished_ts: int = 0
    tools_used: List[str] = field(default_factory=list)
    error: str = ""

    @property
    def duration_sec(self) -> float:
        if not self.finished_ts or not self.started_ts:
            return 0.0
        return (self.finished_ts - self.started_ts) / 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subagent_id": self.subagent_id,
            "prompt": self.prompt[:240],
            "summary": self.summary,
            "facts": self.facts,
            "duration_sec": round(self.duration_sec, 2),
            "tools_used": self.tools_used,
            "error": self.error,
        }


class SubagentRunner:
    """Parent-side API to spawn and collect subagents.

    ``runner_fn`` is a callable provided by the caller – typically a small
    wrapper around ``ConversationOrchestrator.run`` that runs with a fresh
    context. This indirection keeps the subagent system decoupled from the
    orchestrator implementation.
    """

    def __init__(
        self,
        runner_fn: Callable[[str, Dict[str, Any]], Dict[str, Any]],
        *,
        max_concurrent: int = 4,
    ) -> None:
        self._runner = runner_fn
        self._max = max_concurrent
        self._results: Dict[str, SubagentResult] = {}
        self._lock = threading.RLock()

    def spawn(self, prompt: str, *, role: str = "explorer",
              allowed_tools: Optional[List[str]] = None,
              extra_ctx: Optional[Dict[str, Any]] = None) -> str:
        """Spawn a subagent (synchronous convenience: blocks until done)."""
        sub_id = f"sub_{uuid.uuid4().hex[:8]}"
        extra = dict(extra_ctx or {})
        extra.update({"subagent_id": sub_id, "subagent_role": role,
                      "allowed_tools": allowed_tools})
        return self._run_one(sub_id, prompt, extra)

    def spawn_many(self, prompts: List[str], *, role: str = "explorer",
                   allowed_tools: Optional[List[str]] = None,
                   extra_ctx: Optional[Dict[str, Any]] = None) -> List[SubagentResult]:
        """Spawn several subagents concurrently; return list of results."""
        results: List[SubagentResult] = []
        with cf.ThreadPoolExecutor(max_workers=min(self._max, max(1, len(prompts)))) as pool:
            futures: Dict[cf.Future, str] = {}
            for p in prompts:
                sub_id = f"sub_{uuid.uuid4().hex[:8]}"
                extra = dict(extra_ctx or {})
                extra.update({"subagent_id": sub_id, "subagent_role": role,
                              "allowed_tools": allowed_tools})
                fut = pool.submit(self._run_one_returning, sub_id, p, extra)
                futures[fut] = sub_id
            for fut in cf.as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as exc:
                    results.append(SubagentResult(
                        subagent_id=futures[fut], prompt="",
                        summary="", error=f"runner exception: {exc}",
                    ))
        return results

    def get(self, sub_id: str) -> Optional[SubagentResult]:
        with self._lock:
            return self._results.get(sub_id)

    def list(self) -> List[SubagentResult]:
        with self._lock:
            return list(self._results.values())

    # ── Internal ──

    def _run_one(self, sub_id: str, prompt: str, ctx: Dict[str, Any]) -> str:
        self._run_one_returning(sub_id, prompt, ctx)
        return sub_id

    def _run_one_returning(self, sub_id: str, prompt: str, ctx: Dict[str, Any]) -> SubagentResult:
        started = int(time.time())
        result = SubagentResult(
            subagent_id=sub_id, prompt=prompt, summary="",
            started_ts=started,
        )
        try:
            out = self._runner(prompt, ctx) or {}
            result.summary = str(out.get("summary") or out.get("final_message") or "")[:2000]
            result.facts = out.get("facts") or {}
            result.tools_used = list(out.get("tools_used") or [])
        except Exception as exc:
            logger.exception("subagent %s failed", sub_id)
            result.error = f"{type(exc).__name__}: {exc}"
        result.finished_ts = int(time.time())
        with self._lock:
            self._results[sub_id] = result
        return result
