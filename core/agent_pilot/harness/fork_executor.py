"""Multi-Agent Fork executor for parallel exploration.

Inspired by Claude Code's Fork mode: spawn parallel sub-agents
to explore different approaches to a task, then merge results.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("agent_pilot.fork_executor")


@dataclass
class ForkResult:
    fork_id: str
    approach: str
    status: str  # "ok" / "failed" / "timeout"
    result: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    error: Optional[str] = None
    quality_score: float = 0.0


@dataclass
class ForkPlan:
    task_description: str
    approaches: List[Dict[str, Any]]
    merge_strategy: str = "best_quality"  # "best_quality" / "first_success" / "aggregate"
    timeout_sec: int = 120
    max_parallel: int = 3


class ForkExecutor:
    """Execute multiple approaches in parallel and merge results.

    This executor is opt-in — callers create a ``ForkPlan`` describing
    parallel approaches and a callable that executes each one.  The
    executor fans out, collects results, and merges them according to the
    chosen strategy.
    """

    def __init__(self, max_workers: int = 3) -> None:
        self._max_workers = max_workers
        self._lock = threading.Lock()

    def fork_and_merge(
        self,
        plan: ForkPlan,
        executor_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> ForkResult:
        """Run approaches in parallel, return best result."""
        fork_results: List[ForkResult] = []

        effective_workers = min(self._max_workers, plan.max_parallel)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=effective_workers,
        ) as pool:
            futures: Dict[concurrent.futures.Future[ForkResult], tuple[str, Dict[str, Any]]] = {}
            for approach in plan.approaches:
                fork_id = f"fork_{uuid.uuid4().hex[:8]}"
                future = pool.submit(
                    self._run_fork, fork_id, approach, executor_fn, plan.timeout_sec,
                )
                futures[future] = (fork_id, approach)

            for future in concurrent.futures.as_completed(
                futures, timeout=plan.timeout_sec + 10,
            ):
                fork_id, approach = futures[future]
                try:
                    result = future.result()
                    fork_results.append(result)
                except Exception as e:
                    fork_results.append(ForkResult(
                        fork_id=fork_id,
                        approach=str(approach.get("name", "unknown")),
                        status="failed",
                        error=str(e),
                    ))

        return self._merge(fork_results, plan.merge_strategy)

    def _run_fork(
        self,
        fork_id: str,
        approach: Dict[str, Any],
        executor_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
        timeout: int,
    ) -> ForkResult:
        t0 = time.time()
        try:
            result = executor_fn(approach)
            return ForkResult(
                fork_id=fork_id,
                approach=str(approach.get("name", "unknown")),
                status="ok",
                result=result,
                duration_ms=int((time.time() - t0) * 1000),
                quality_score=result.get("quality_score", 0.5),
            )
        except Exception as e:
            return ForkResult(
                fork_id=fork_id,
                approach=str(approach.get("name", "unknown")),
                status="failed",
                error=str(e),
                duration_ms=int((time.time() - t0) * 1000),
            )

    def _merge(self, results: List[ForkResult], strategy: str) -> ForkResult:
        ok_results = [r for r in results if r.status == "ok"]

        if not ok_results:
            return results[0] if results else ForkResult(
                fork_id="none", approach="none", status="failed", error="no results",
            )

        if strategy == "first_success":
            return ok_results[0]

        if strategy == "best_quality":
            return max(ok_results, key=lambda r: r.quality_score)

        if strategy == "aggregate":
            merged = ForkResult(
                fork_id="merged",
                approach="aggregate",
                status="ok",
                result={
                    "approaches": [r.result for r in ok_results],
                    "count": len(ok_results),
                },
                quality_score=sum(r.quality_score for r in ok_results) / len(ok_results),
            )
            return merged

        return ok_results[0]
