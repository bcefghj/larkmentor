"""Workforce 三 Agent Harness（Anthropic 2026-03 长任务最佳实践）.

GAN-inspired:
  - Planner   : 1-4 句 prompt → 完整产品 spec
  - Generator : Sprint 一次一个，写完自评再交 QA
  - Evaluator : 4 维评分（quality / originality / craft / functionality），打分低于阈值则返工
  - Sprint 合约: Generator 与 Evaluator 在写代码前先谈定 "什么算 done"
"""

from pilot.capability.workforce.planner_agent import PlannerAgent  # noqa: F401
from pilot.capability.workforce.generator_agent import GeneratorAgent  # noqa: F401
from pilot.capability.workforce.evaluator_agent import EvaluatorAgent, EvalScore  # noqa: F401
from pilot.capability.workforce.sprint_contract import SprintContract  # noqa: F401
from pilot.capability.workforce.clarifier import Clarifier  # noqa: F401

__all__ = [
    "PlannerAgent",
    "GeneratorAgent",
    "EvaluatorAgent",
    "EvalScore",
    "SprintContract",
    "Clarifier",
]
