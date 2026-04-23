"""Multi-Agent Patterns (Claude Code 4 种核心 pattern)。

1. Fan-out: 1 输入 → N subagent 并行 → 父聚合
2. Pipeline: 阶段串行，阶段内并行
3. Map-Reduce: N agent 各处理一片 → reduce
4. Specialist Delegation: 按专业分工

Anthropic 90.2% 提升的核心机制。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from ..subagent import SubagentRunner, SubagentSpec, SubagentResult, default_subagent_runner


async def fan_out(
    specs: List[SubagentSpec], *,
    runner: Optional[SubagentRunner] = None,
    aggregator: Optional[Callable[[List[SubagentResult]], str]] = None,
) -> Dict[str, Any]:
    """Pattern 1: Fan-out. All subagents run in parallel, parent aggregates."""
    runner = runner or default_subagent_runner()
    results = await runner.spawn_parallel(specs)
    if aggregator:
        summary = aggregator(results)
    else:
        summary = "\n\n".join(
            f"[{r.agent_type} / {r.status}]\n{r.summary}" for r in results
        )
    return {
        "pattern": "fan_out",
        "results": [r.__dict__ for r in results],
        "aggregated_summary": summary,
        "total_duration_ms": max((r.duration_ms for r in results), default=0),
        "ok_count": sum(1 for r in results if r.status == "ok"),
    }


async def pipeline(
    stages: List[List[SubagentSpec]], *,
    runner: Optional[SubagentRunner] = None,
) -> Dict[str, Any]:
    """Pattern 2: Pipeline. Stages are sequential; within a stage, specs run parallel."""
    runner = runner or default_subagent_runner()
    all_stage_results: List[List[SubagentResult]] = []
    total_duration = 0
    for stage_idx, specs in enumerate(stages):
        # Inject previous stage summary into each spec's task
        if all_stage_results:
            prev_summary = "\n".join(r.summary for r in all_stage_results[-1] if r.status == "ok")[:2000]
            for s in specs:
                s.task = f"Previous stage results:\n{prev_summary}\n\n---\nYour task: {s.task}"
        results = await runner.spawn_parallel(specs)
        all_stage_results.append(results)
        total_duration += max((r.duration_ms for r in results), default=0)
    return {
        "pattern": "pipeline",
        "stages": [
            [r.__dict__ for r in stage] for stage in all_stage_results
        ],
        "total_duration_ms": total_duration,
    }


async def map_reduce(
    items: List[Any], *,
    map_instruction: str,
    reduce_instruction: str,
    runner: Optional[SubagentRunner] = None,
    chunk_size: int = 10,
    model: str = "",
) -> Dict[str, Any]:
    """Pattern 3: Map-Reduce. Split items into chunks, map in parallel, then reduce."""
    runner = runner or default_subagent_runner()
    # Chunk
    chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

    # Map
    map_specs = [
        SubagentSpec(
            agent_type=f"mapper-{i}",
            task=f"{map_instruction}\n\nItems:\n" + "\n".join(str(x) for x in chunk),
            instruction="You are a map worker. Process items and return a compact JSON summary.",
            model=model,
        )
        for i, chunk in enumerate(chunks)
    ]
    map_results = await runner.spawn_parallel(map_specs)

    # Reduce
    map_summary = "\n---\n".join(r.summary for r in map_results if r.status == "ok")
    reduce_spec = SubagentSpec(
        agent_type="reducer",
        task=f"{reduce_instruction}\n\nMapped results:\n{map_summary[:8000]}",
        instruction="You are a reducer. Aggregate the mapped results into a final coherent answer.",
        model=model,
    )
    reduce_result = await runner.spawn(reduce_spec)
    return {
        "pattern": "map_reduce",
        "chunks": len(chunks),
        "map_results": [r.__dict__ for r in map_results],
        "reduced_answer": reduce_result.summary,
    }


async def specialist_delegation(
    task: str, *,
    specialists: Dict[str, str],  # {role: instruction}
    runner: Optional[SubagentRunner] = None,
) -> Dict[str, Any]:
    """Pattern 4: Specialist Delegation. Each specialist handles one aspect."""
    runner = runner or default_subagent_runner()
    specs = [
        SubagentSpec(
            agent_type=role,
            task=f"Main task: {task}\n\nYour role: {role}\nYour focus: {instruction}",
            instruction=f"You are a {role} specialist. {instruction}",
        )
        for role, instruction in specialists.items()
    ]
    results = await runner.spawn_parallel(specs)
    return {
        "pattern": "specialist_delegation",
        "specialists": list(specialists.keys()),
        "results": [r.__dict__ for r in results],
        "combined_summary": "\n---\n".join(
            f"# {r.agent_type}\n{r.summary}" for r in results if r.status == "ok"
        ),
    }


# ─── Sync wrappers for non-async callers ───

def sync_fan_out(specs: List[SubagentSpec], **kwargs) -> Dict[str, Any]:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(fan_out(specs, **kwargs))
    finally:
        loop.close()


def sync_pipeline(stages: List[List[SubagentSpec]], **kwargs) -> Dict[str, Any]:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(pipeline(stages, **kwargs))
    finally:
        loop.close()


def sync_map_reduce(items: List[Any], *, map_instruction: str, reduce_instruction: str, **kwargs) -> Dict[str, Any]:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(map_reduce(
            items, map_instruction=map_instruction, reduce_instruction=reduce_instruction, **kwargs
        ))
    finally:
        loop.close()


def sync_specialist_delegation(task: str, *, specialists: Dict[str, str], **kwargs) -> Dict[str, Any]:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(specialist_delegation(task, specialists=specialists, **kwargs))
    finally:
        loop.close()
