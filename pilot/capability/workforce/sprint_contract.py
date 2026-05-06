"""Sprint 合约 — Generator 与 Evaluator 在写之前先谈定 'done'.

Anthropic 长任务实践：
  - 高层 spec 不写实现细节
  - 每个 sprint 由 generator 提出实现 + 验收标准，evaluator 审核
  - 双方达成一致后开干，避免边写边返工
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SprintContract:
    sprint_id: str = field(default_factory=lambda: f"sprint_{int(time.time())}_{uuid.uuid4().hex[:6]}")
    title: str = ""
    goal: str = ""
    sprint_index: int = 0

    # Generator 提案
    proposed_implementation: str = ""
    deliverables: list[str] = field(default_factory=list)
    test_criteria: list[str] = field(default_factory=list)

    # Evaluator 审核
    accepted: bool = False
    accepted_ts: int = 0
    feedback: str = ""

    created_ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sprint_id": self.sprint_id,
            "title": self.title,
            "goal": self.goal,
            "sprint_index": self.sprint_index,
            "proposed_implementation": self.proposed_implementation,
            "deliverables": self.deliverables,
            "test_criteria": self.test_criteria,
            "accepted": self.accepted,
            "accepted_ts": self.accepted_ts,
            "feedback": self.feedback,
            "created_ts": self.created_ts,
        }

    def accept(self, feedback: str = "") -> None:
        self.accepted = True
        self.accepted_ts = int(time.time())
        self.feedback = feedback

    def reject(self, feedback: str) -> None:
        self.accepted = False
        self.feedback = feedback
