"""PlannerService · 把 ContextPack 翻译成 DAG，并自动选推理模式.

设计要点：
1. **复用现有 ``..planner.PilotPlanner``** —— 不重写已有 LLM/启发式拆解逻辑
2. **自动选 5 推理模式**（ReAct / CoT / Reflection / Debate / ToT）—— 写在
   ``select_reasoning_pattern`` 函数里，规则可解释
3. **绑定到 ``domain.Plan``** —— 同时填充 ``reasoning_pattern`` 字段，便于
   dashboard 可视化"为什么选了这个模式"

产物的 ``Plan`` 与 ``Task.plan`` 字段对齐，下游 ``OrchestratorService`` 直接消费。
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from ..domain import (
    ContextPack,
    Plan as DomainPlan,
    PlanStep as DomainPlanStep,
    Task,
)

logger = logging.getLogger("pilot.application.planner_service")


class ReasoningPattern(str, Enum):
    """5 推理模式（README 中 5 patterns 真实落地）."""

    REACT = "react"             # 简单·单步推理（默认 fast path）
    COT = "cot"                 # Chain-of-Thought · 中等单轮
    REFLECTION = "reflection"   # 含 Builder-Validator 反思
    DEBATE = "debate"           # 双方辩论收敛
    TOT = "tot"                 # Tree-of-Thoughts · 探索多分支


@dataclass
class PatternSelection:
    pattern: ReasoningPattern
    reason: str
    confidence: float = 0.0


# ── 自动选模式 ─────────────────────────────────────────────────────────────


_TOT_KEYWORDS = ("探索", "对比方案", "若干种", "几条路径", "可能性", "几个角度")
_DEBATE_KEYWORDS = ("辩论", "选 A 还是 B", "A 还是 B", "正反方", "权衡", "决策")
_REFLECT_KEYWORDS = ("校核", "审查", "审稿", "评审", "复审", "review")
_FANOUT_KEYWORDS = ("并行", "同时", "三种风格", "多个版本", "几个版本")


def select_reasoning_pattern(task: Task, ctx: ContextPack,
                              *, default: ReasoningPattern = ReasoningPattern.COT
                              ) -> PatternSelection:
    """规则化选择 5 推理模式之一.

    策略：
    - 短指令（intent < 25 字）+ 单一动作 → REACT
    - 触发"探索 / 几种 / 对比方案" → ToT
    - 触发"辩论 / 决策 / A 还是 B" → DEBATE
    - 高合规要求（must_validate）→ REFLECTION（强制 Builder-Validator）
    - 默认中等任务 → CoT
    """
    text = (task.intent or "") + " " + (ctx.task_goal or "")
    text_lower = text.lower()

    if any(k in text for k in _TOT_KEYWORDS) or any(k in text_lower for k in ("explore", "branch")):
        return PatternSelection(ReasoningPattern.TOT,
                                reason="意图含探索/分支语义")

    if any(k in text for k in _DEBATE_KEYWORDS) or any(k in text_lower for k in ("debate", "vs ")):
        return PatternSelection(ReasoningPattern.DEBATE,
                                reason="意图含辩论/决策语义")

    if any(k in text for k in _REFLECT_KEYWORDS) or ctx.constraints.must_validate:
        return PatternSelection(ReasoningPattern.REFLECTION,
                                reason="must_validate=True · Builder-Validator 强制启用")

    if len(task.intent or "") < 25 and not any(k in text for k in _FANOUT_KEYWORDS):
        return PatternSelection(ReasoningPattern.REACT,
                                reason="短指令 + 单一明确动作")

    return PatternSelection(default, reason="默认中等单轮 CoT")


# ── PlannerService ────────────────────────────────────────────────────────


# Backend planner adapter type: (intent, **kwargs) -> {"plan_id": str, "steps": [{...}]}
PlannerAdapter = Callable[[str], Any]


class PlannerService:
    """绑定 Pilot 主流程的 Planner facade."""

    def __init__(self, *, planner_factory: Optional[PlannerAdapter] = None) -> None:
        # planner_factory 默认是现有 PilotPlanner，可注入 mock
        self._planner_factory = planner_factory

    def _backend_planner(self):
        if self._planner_factory is not None:
            return self._planner_factory
        try:
            from ..planner import PilotPlanner
            return PilotPlanner()
        except Exception:
            return None

    def plan_for_task(self, task: Task, *, allow_clarify: bool = True) -> DomainPlan:
        """主入口：从 Task + ContextPack 生成 DomainPlan."""
        if task.context_pack is None:
            raise ValueError("Task.context_pack must be set before planning")

        sel = select_reasoning_pattern(task, task.context_pack)
        task.log(agent="@pilot", kind="thought",
                  content=f"select_reasoning_pattern → {sel.pattern.value} ({sel.reason})")

        backend = self._backend_planner()
        steps: List[DomainPlanStep] = []

        if backend is not None:
            try:
                # 现有 PilotPlanner.plan(intent, user_open_id, meta, allow_clarify)
                plan = backend.plan(
                    task.intent,
                    user_open_id=task.owner_lock.owner_open_id,
                    meta={"task_id": task.task_id,
                          "reasoning_pattern": sel.pattern.value,
                          "ctx_pack_id": task.context_pack.pack_id},
                    allow_clarify=allow_clarify,
                )
                # 把现有 PlanStep 适配到 DomainPlanStep
                for ps in plan.steps:
                    steps.append(DomainPlanStep(
                        step_id=ps.step_id,
                        tool=ps.tool,
                        description=ps.description,
                        args=ps.args,
                        depends_on=list(ps.depends_on),
                        parallel_group=ps.parallel_group or "",
                        status=getattr(ps, "status", "pending"),
                    ))
            except Exception as e:
                logger.warning("backend planner failed, falling back to heuristic: %s", e)

        if not steps:
            steps = self._heuristic_plan(task)

        domain_plan = DomainPlan(
            plan_id=f"plan-{uuid.uuid4().hex[:10]}",
            task_id=task.task_id,
            owner_open_id=task.owner_lock.owner_open_id,
            intent=task.intent,
            steps=steps,
            reasoning_pattern=sel.pattern.value,
            notes=sel.reason,
        )
        task.plan = domain_plan
        return domain_plan

    @staticmethod
    def _heuristic_plan(task: Task) -> List[DomainPlanStep]:
        """LLM 不可用时的纯规则 fallback."""
        cp = task.context_pack
        primary = (cp.output_requirements.primary or "doc") if cp else "doc"

        steps: List[DomainPlanStep] = []
        steps.append(DomainPlanStep(
            step_id="s1", tool="im.fetch_thread",
            description="拉取 IM 上下文（已包含在 ContextPack 中）",
            args={"limit": 50},
        ))
        if primary == "ppt":
            steps.append(DomainPlanStep(
                step_id="s2", tool="doc.create",
                description="先生成文档大纲",
                args={"title": task.title or task.intent[:30]},
                depends_on=["s1"],
            ))
            steps.append(DomainPlanStep(
                step_id="s3", tool="slide.generate",
                description="基于文档生成 PPT",
                args={"outline_from": "s2"},
                depends_on=["s2"],
            ))
        elif primary == "canvas":
            steps.append(DomainPlanStep(
                step_id="s2", tool="canvas.create",
                description="创建画板",
                args={"title": task.title or task.intent[:30]},
                depends_on=["s1"],
            ))
        else:
            steps.append(DomainPlanStep(
                step_id="s2", tool="doc.create",
                description="创建飞书 Docx",
                args={"title": task.title or task.intent[:30]},
                depends_on=["s1"],
            ))
            steps.append(DomainPlanStep(
                step_id="s3", tool="doc.append",
                description="写入大纲与正文",
                args={"doc_token": "${s2.doc_token}"},
                depends_on=["s2"],
            ))
        steps.append(DomainPlanStep(
            step_id=f"s{len(steps)+1}",
            tool="archive.bundle",
            description="汇总产出 + 分享链接",
            args={},
            depends_on=[steps[-1].step_id],
        ))
        return steps


__all__ = [
    "PlannerService",
    "PatternSelection",
    "ReasoningPattern",
    "select_reasoning_pattern",
]
