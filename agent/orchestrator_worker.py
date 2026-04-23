"""Orchestrator-Worker Pattern (Anthropic 90.2% 提升核心)

Lead Agent (Orchestrator, MiniMax M2.7) 分解任务 + 协调
    ↓ spawn
Domain Specialists (Workers, 豆包) 按领域并行执行
    ↓ spawn (optional)
Tool Workers (DeepSeek) 执行 bulk 任务

关键原则:
- Lead 不做脏活，只做高层规划和聚合
- Workers 单一职责
- Parallel exploration: 3-5 workers + 每个 workers 可并行调 3+ tools
- Context 完全隔离（subagent 不继承父 context）
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .subagent import SubagentRunner, SubagentSpec, SubagentResult, default_subagent_runner
from .providers import default_providers

logger = logging.getLogger("agent.orchestrator_worker")


@dataclass
class WorkerRole:
    name: str
    instruction: str
    model_kind: str = "chinese_chat"  # routing key to providers.py
    max_turns: int = 3


@dataclass
class OrchestratorResult:
    lead_plan: str
    worker_results: List[SubagentResult]
    final_synthesis: str
    total_duration_ms: int
    cost_cny: float
    tokens_used: int
    ok: bool


PREDEFINED_TEAMS: Dict[str, List[WorkerRole]] = {
    "pilot": [
        WorkerRole("planner", "生成详细的 DAG 步骤，每步 JSON：step_id, tool, args, depends_on", "planning"),
        WorkerRole("estimator", "估算每步的 token 成本、预计时长、工具调用次数", "summary"),
        WorkerRole("risk_checker", "找依赖冲突、资源竞争、潜在失败点", "chinese_chat"),
        WorkerRole("verifier", "根据 5 道 Quality Gate 审查方案", "validation"),
    ],
    "doc": [
        WorkerRole("researcher", "调用 memory/wiki/doc 搜集相关素材", "research"),
        WorkerRole("outliner", "生成清晰章节大纲（标题+要点）", "chinese_chat"),
        WorkerRole("writer", "撰写正文，专业、流畅、带示例", "reasoning"),
        WorkerRole("reviewer", "风格一致性审查 + 改写建议", "review"),
        WorkerRole("citation", "给每条 claim 标注出处，生成 references", "review"),
        WorkerRole("critic", "Builder-Validator：独立审稿，给出改进清单", "critique"),
    ],
    "slides": [
        WorkerRole("extractor", "从文档抽取关键点 → 大纲", "chinese_chat"),
        WorkerRole("designer", "每页布局 + 配色建议", "reasoning"),
        WorkerRole("visualizer", "生成 Mermaid DSL → PNG 图", "chinese_chat"),
        WorkerRole("copywriter", "每页标题与要点精炼", "summary"),
        WorkerRole("rehearser", "生成讲稿 + 语气标记 + 预计时长", "chinese_chat"),
        WorkerRole("a11y_reviewer", "可读性/对比度/字体大小审查", "validation"),
    ],
    "archive": [
        WorkerRole("summarizer", "生成一句话摘要 + 300 字摘要", "summary"),
        WorkerRole("wiki_writer", "写 Wiki 节点的 markdown", "chinese_chat"),
        WorkerRole("file_exporter", "生成 PDF 导出说明", "summary"),
        WorkerRole("share_link_signer", "生成 HMAC 签名参数", "validation"),
    ],
}


class OrchestratorWorker:
    """Hierarchical Lead + Workers (Anthropic 90.2% pattern)."""

    def __init__(
        self, *,
        runner: Optional[SubagentRunner] = None,
    ) -> None:
        self.runner = runner or default_subagent_runner()
        self.providers = default_providers()

    async def run(
        self, task: str, *,
        team: str = "pilot",
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> OrchestratorResult:
        """Full orchestrator-worker run."""
        start = time.time()
        roles = PREDEFINED_TEAMS.get(team)
        if not roles:
            roles = [WorkerRole(
                name="worker",
                instruction="Execute the task directly.",
            )]

        # Step 1: Lead (MiniMax M2.7) generates plan + delegates
        lead_plan = await self._lead_plan(task, roles, extra_context or {})

        # Step 2: spawn workers in parallel
        specs: List[SubagentSpec] = []
        for role in roles:
            # Custom task for each worker from lead plan
            worker_task = self._worker_subtask(task, role, lead_plan, extra_context or {})
            specs.append(SubagentSpec(
                agent_type=role.name,
                task=worker_task,
                instruction=role.instruction,
                max_turns=role.max_turns,
            ))

        worker_results = await self.runner.spawn_parallel(
            specs,
            executor=self._role_executor_factory(roles),
        )

        # Step 3: Lead synthesizes
        synthesis = await self._lead_synthesize(task, worker_results)

        duration = int((time.time() - start) * 1000)
        cost = self.providers.current_plan_cost()
        return OrchestratorResult(
            lead_plan=lead_plan,
            worker_results=worker_results,
            final_synthesis=synthesis,
            total_duration_ms=duration,
            cost_cny=cost,
            tokens_used=sum(r.tokens_used for r in worker_results),
            ok=any(r.status == "ok" for r in worker_results),
        )

    async def _lead_plan(self, task: str, roles: List[WorkerRole], ctx: Dict) -> str:
        prompt = (
            f"You are a Lead Agent orchestrating specialists to accomplish a task.\n\n"
            f"Task: {task}\n\n"
            f"Available workers:\n"
            + "\n".join(f"- @{r.name}: {r.instruction}" for r in roles) +
            f"\n\nExtra context: {json.dumps(ctx, ensure_ascii=False)[:500]}\n\n"
            f"Step 1: break the task into worker-sized pieces.\n"
            f"Step 2: for each worker, specify what they should focus on.\n"
            f"Respond as JSON: {{\"plan\": \"overall strategy\", \"assignments\": {{\"@worker\": \"subtask\"}}}}"
        )
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.providers.chat(
            messages=[{"role": "user", "content": prompt}],
            task_kind="planning", max_tokens=1200,
        ))

    def _worker_subtask(self, main_task: str, role: WorkerRole, lead_plan: str, ctx: Dict) -> str:
        return (
            f"Main task (from user): {main_task}\n\n"
            f"Lead's overall plan:\n{lead_plan[:1200]}\n\n"
            f"Your role: @{role.name}\n"
            f"Your instructions: {role.instruction}\n\n"
            f"Extra context keys: {list(ctx.keys())}\n\n"
            f"Focus only on your role. Return a structured summary."
        )

    def _role_executor_factory(self, roles: List[WorkerRole]) -> Callable:
        role_map = {r.name: r for r in roles}
        providers = self.providers

        def _exec(spec: SubagentSpec) -> Dict[str, Any]:
            role = role_map.get(spec.agent_type)
            kind = role.model_kind if role else "chinese_chat"
            out = providers.chat(
                messages=[
                    {"role": "system", "content": spec.instruction},
                    {"role": "user", "content": spec.task},
                ],
                task_kind=kind, max_tokens=1500,
            )
            return {
                "summary": out[:3000],
                "tool_calls": 0,
                "tokens_used": len(out) // 4,
                "metadata": {"role": spec.agent_type, "model_kind": kind},
            }
        return _exec

    async def _lead_synthesize(self, task: str, results: List[SubagentResult]) -> str:
        pieces = []
        for r in results:
            if r.status == "ok":
                pieces.append(f"# @{r.agent_type}\n{r.summary}")
        prompt = (
            f"Task: {task}\n\n"
            f"Worker outputs:\n\n" + "\n\n---\n\n".join(pieces) + "\n\n"
            f"Synthesize a final, coherent answer combining the best of all workers. "
            f"Resolve any disagreements. Output in Chinese if the task is Chinese."
        )
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.providers.chat(
            messages=[{"role": "user", "content": prompt}],
            task_kind="reasoning", max_tokens=2000,
        ))

    def sync_run(self, task: str, *, team: str = "pilot", **kwargs) -> OrchestratorResult:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.run(task, team=team, **kwargs))
        finally:
            loop.close()


_singleton: Optional[OrchestratorWorker] = None


def default_orchestrator_worker() -> OrchestratorWorker:
    global _singleton
    if _singleton is None:
        _singleton = OrchestratorWorker()
    return _singleton
