"""Evaluator Agent — 4 维评分 + 拒绝/接受 sprint.

Anthropic 长任务实践：
  - quality: 整体连贯性 / 是否符合 spec
  - originality: 是否有具体的创意决策（避免 AI slop）
  - craft: 排版/格式/字数
  - functionality: 链接是否可用、文件是否能打开

每维度 0-100；任何一维 < 60 即拒绝。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pilot.capability.workforce.sprint_contract import SprintContract

logger = logging.getLogger("pilot.workforce.evaluator")


@dataclass
class EvalScore:
    quality: int = 0
    originality: int = 0
    craft: int = 0
    functionality: int = 0
    notes: str = ""
    failed_criteria: list[str] = field(default_factory=list)

    def total(self) -> int:
        return self.quality + self.originality + self.craft + self.functionality

    def is_passing(self, threshold: int = 60) -> bool:
        return all(v >= threshold for v in [
            self.quality, self.originality, self.craft, self.functionality
        ])

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality": self.quality,
            "originality": self.originality,
            "craft": self.craft,
            "functionality": self.functionality,
            "total": self.total(),
            "is_passing": self.is_passing(),
            "notes": self.notes,
            "failed_criteria": self.failed_criteria,
        }


class EvaluatorAgent:
    async def review_contract(self, contract: SprintContract) -> bool:
        """合约阶段：检查 deliverables 与 test_criteria 是否合理."""
        if not contract.deliverables or not contract.test_criteria:
            contract.reject("deliverables 或 test_criteria 缺失")
            return False
        if len(contract.test_criteria) < 2:
            contract.reject("test_criteria 至少 2 条")
            return False
        contract.accept("contract OK")
        return True

    async def evaluate(self, *, contract: SprintContract, sprint_result: dict[str, Any]) -> EvalScore:
        """对 sprint 产出做评分."""
        score = EvalScore(quality=70, originality=70, craft=70, functionality=70)

        # 简单规则评分（生产中接 LLM/Playwright）
        title = (contract.title or "").lower()
        if "文档" in contract.title or "doc" in title:
            md_chars = sprint_result.get("markdown_chars", 0)
            wrote = sprint_result.get("wrote_blocks", 0)
            if md_chars >= 1500:
                score.quality = 88
            elif md_chars >= 800:
                score.quality = 70
            else:
                score.quality = 40
                score.failed_criteria.append(f"字数不足: {md_chars} < 1500")
            if wrote > 0:
                score.functionality = 85

        elif "canvas" in title or "画布" in contract.title or "架构" in contract.title:
            nodes = sprint_result.get("node_count", 0)
            if nodes >= 4:
                score.quality = 80
            else:
                score.quality = 50
                score.failed_criteria.append(f"节点数不足: {nodes} < 4")
            score.functionality = 80 if sprint_result.get("mermaid") else 40

        elif "ppt" in title or "演示" in contract.title or "幻灯" in contract.title:
            pages = sprint_result.get("pages", 0)
            if pages >= 6:
                score.quality = 85
                score.craft = 80
            else:
                score.quality = 50
                score.failed_criteria.append(f"页数不足: {pages} < 6")
            if sprint_result.get("pptx_path"):
                score.functionality = 90

        elif "archive" in title or "归档" in contract.title:
            items = sprint_result.get("items_count", 0)
            score.functionality = 90 if items >= 1 else 30
            if items < 1:
                score.failed_criteria.append("没有 items 被归档")

        # originality 由 LLM 判断（V1 简化为常数）
        score.originality = 75

        score.notes = f"sprint #{contract.sprint_index} {contract.title} 评估完成"
        return score
