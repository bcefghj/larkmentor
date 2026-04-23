"""Content Critic · Builder-Validator 分离中的 Validator 基类。

给 Builder 输出打分 + 提供改进建议。避免 Builder 审自己的盲点。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent.validators.critic")


@dataclass
class CritiqueReport:
    score: float  # 0-1
    issues: List[str]
    improvements: List[str]
    strengths: List[str]
    verdict: str  # "pass" / "minor_issues" / "needs_rework"
    raw: str = ""


class ContentCritic:
    """Independent critic agent - never does writing, only reviews."""

    def review(
        self, content: str, *,
        task: str = "",
        rubric: Optional[List[str]] = None,
    ) -> CritiqueReport:
        default_rubric = [
            "是否完整回答任务要求",
            "逻辑是否清晰无矛盾",
            "关键数据/事实是否准确",
            "可读性与语言流畅度",
            "结构是否合理",
        ]
        rubric = rubric or default_rubric

        prompt = (
            f"你是一个独立的内容审查专家。你永远不写内容，只严格审查别人的输出。\n\n"
            f"原任务：{task}\n\n"
            f"待审内容：\n{content[:4000]}\n\n"
            f"审查维度：\n" + "\n".join(f"- {r}" for r in rubric) + "\n\n"
            f"严格审查并以 JSON 返回：\n"
            f'{{"score": 0-1 浮点数, "issues": ["..."], "improvements": ["..."], "strengths": ["..."], "verdict": "pass" | "minor_issues" | "needs_rework"}}'
        )
        try:
            from ..providers import default_providers
            out = default_providers().chat(
                messages=[{"role": "user", "content": prompt}],
                task_kind="critique",
                max_tokens=800,
            )
        except Exception as e:
            logger.warning("critic provider call failed: %s", e)
            return CritiqueReport(score=0.0, issues=[str(e)], improvements=[], strengths=[], verdict="needs_rework")

        raw = out
        cleaned = out.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            data = json.loads(cleaned)
            return CritiqueReport(
                score=float(data.get("score", 0)),
                issues=data.get("issues", []),
                improvements=data.get("improvements", []),
                strengths=data.get("strengths", []),
                verdict=data.get("verdict", "minor_issues"),
                raw=raw,
            )
        except Exception as e:
            logger.debug("critic JSON parse failed: %s", e)
            # Fallback: heuristic score
            has_issue_words = len(re.findall(r'(?:issue|problem|错误|不足|缺少|missing)', out, re.IGNORECASE))
            score = max(0.0, 1.0 - 0.15 * has_issue_words)
            return CritiqueReport(
                score=score, issues=[out[:200]], improvements=[], strengths=[],
                verdict="pass" if score > 0.7 else "minor_issues",
                raw=raw,
            )


_singleton: Optional[ContentCritic] = None


def default_content_critic() -> ContentCritic:
    global _singleton
    if _singleton is None:
        _singleton = ContentCritic()
    return _singleton
