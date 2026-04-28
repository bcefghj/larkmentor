"""Task mentor · active clarification mode.

Algorithm (inspired by ``clarify-first`` and arXiv 2603.26233):
1. LLM scores ``ambiguity`` 0-1 over 4 dims (scope / deadline / stakeholder /
   success_criteria) and proposes the 1-2 questions with the highest
   information gain.
2. If ambiguity > threshold (default 0.5) → output the 2 questions.
   Otherwise → output a structured "understanding + plan + risks" packet
   ready to send to the assigner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from config import Config
from llm.llm_client import chat_json
from llm.prompts import MENTOR_TASK_CLARIFY_PROMPT

from . import knowledge_base as kb

logger = logging.getLogger("flowguard.mentor.task")


@dataclass
class TaskClarification:
    ambiguity: float = 0.0
    missing_dims: List[str] = field(default_factory=list)
    suggested_questions: List[str] = field(default_factory=list)
    task_understanding: str = ""
    delivery_plan: str = ""
    risks: List[str] = field(default_factory=list)
    ready_to_start: bool = False
    citations: List[str] = field(default_factory=list)
    fallback: bool = False

    @property
    def needs_clarification(self) -> bool:
        try:
            threshold = Config.MENTOR_AMBIGUITY_THRESHOLD
        except Exception:
            threshold = 0.5
        return self.ambiguity > threshold

    def to_dict(self) -> dict:
        return {
            "ambiguity": round(self.ambiguity, 3),
            "missing_dims": self.missing_dims,
            "suggested_questions": self.suggested_questions,
            "task_understanding": self.task_understanding,
            "delivery_plan": self.delivery_plan,
            "risks": self.risks,
            "ready_to_start": self.ready_to_start,
            "citations": self.citations,
            "fallback": self.fallback,
            "needs_clarification": self.needs_clarification,
        }


_VALID_DIMS = {"scope", "deadline", "stakeholder", "success_criteria"}


def _safe_fallback(task: str) -> TaskClarification:
    return TaskClarification(
        ambiguity=0.7,
        missing_dims=["scope", "deadline"],
        suggested_questions=[
            "请问这个需求的最终交付物是什么形式（文档/代码/PPT）？",
            "希望什么时候完成？是否有 deadline？",
        ],
        task_understanding="",
        delivery_plan="",
        risks=["模型暂不可用，建议人工再次确认"],
        ready_to_start=False,
        fallback=True,
    )


def clarify(open_id: str, task_description: str, *, assigner: str = "上级") -> TaskClarification:
    """Run the clarification flow for a task. Always returns a result."""
    if not task_description or not task_description.strip():
        return TaskClarification(
            ambiguity=1.0,
            missing_dims=list(_VALID_DIMS),
            suggested_questions=["可以详细描述一下这个任务吗？"],
        )

    hits = kb.search(open_id, task_description[:120])
    org_context = kb.render_citations(hits) if hits else "（无组织文档可用）"
    citations = [h.citation_tag() for h in hits]

    prompt = MENTOR_TASK_CLARIFY_PROMPT.format(
        org_context=org_context,
        task_description=task_description,
        assigner=assigner,
    )

    try:
        result = chat_json(prompt, temperature=0.2)
    except Exception as e:  # noqa: BLE001
        logger.warning("task_llm_fail err=%s", e)
        result = {}

    if not result:
        out = _safe_fallback(task_description)
        out.citations = citations
        return out

    try:
        ambiguity = float(result.get("ambiguity", 0.5))
    except Exception:
        ambiguity = 0.5
    ambiguity = max(0.0, min(1.0, ambiguity))

    missing_raw = result.get("missing_dims") or []
    missing = [d for d in missing_raw if d in _VALID_DIMS]

    questions_raw = result.get("suggested_questions") or []
    questions = [str(q) for q in questions_raw if str(q).strip()][:2]

    risks_raw = result.get("risks") or []
    risks = [str(r) for r in risks_raw if str(r).strip()][:5]

    return TaskClarification(
        ambiguity=ambiguity,
        missing_dims=missing,
        suggested_questions=questions,
        task_understanding=str(result.get("task_understanding", "")),
        delivery_plan=str(result.get("delivery_plan", "")),
        risks=risks,
        ready_to_start=bool(result.get("ready_to_start", False)),
        citations=citations,
        fallback=False,
    )
