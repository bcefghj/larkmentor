"""Plan · DAG 计划（与现有 ``..planner.Plan`` 互补）.

现有 ``..planner.Plan`` 有大量 v2 时代实现（DAG 拓扑/parallel_group/depends_on
等）。本模块只是新加的 **owner-aware Plan** 视图，兼容现有 planner 输出，
并为 application 层 ``orchestrator_service`` 提供领域统一接口。

如果你只读现有 planner，仍能正常工作。如果你写新代码，请用本模块的
``Plan``（带 owner / task_id 双向引用）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class PlanStep:
    step_id: str
    tool: str
    description: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    parallel_group: str = ""
    # 执行态
    status: str = "pending"
    started_ts: int = 0
    finished_ts: int = 0
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class Plan:
    """Domain Plan: 显式带 task_id + owner."""

    plan_id: str
    task_id: str                    # 反向指向 Task
    owner_open_id: str
    intent: str
    steps: List[PlanStep] = field(default_factory=list)
    created_ts: int = 0
    notes: str = ""                  # planner 自由备注（推理模式选择理由等）
    reasoning_pattern: str = "react"  # "react" / "reflection" / "cot" / "debate" / "tot"

    def step_count(self) -> int:
        return len(self.steps)

    def find_step(self, step_id: str) -> PlanStep | None:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None


__all__ = ["Plan", "PlanStep"]
