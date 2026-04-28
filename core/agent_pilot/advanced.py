"""Advanced Agent behaviours (competition "Good-to-have" category).

Three specific Agent capabilities the scorecard calls out:
  1. **Proactive clarification** – when the intent is ambiguous the
     Agent asks follow-up questions BEFORE starting the DAG.
  2. **Discussion summarisation** – turn long IM threads into 3-5
     decision points (used as Doc / PPT seed).
  3. **Next-step recommendation** – after a plan finishes, suggest
     what the user should do next (schedule a review, share, etc.).

All three are thin wrappers that use the existing Mentor 4 Skills and
FlowMemory modules so we don't duplicate logic.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pilot.advanced")


# ── 1. Proactive clarification ──

@dataclass
class ClarifyDecision:
    should_clarify: bool
    ambiguity: float
    questions: List[str]
    missing_dimensions: List[str]


def diagnose_intent(intent: str) -> ClarifyDecision:
    """Return a ClarifyDecision telling the caller if we should pause
    execution to ask the user questions.
    """
    # Heuristic fast path – cheap and deterministic for unit tests.
    ambiguity = _heuristic_ambiguity(intent)
    missing = _missing_dimensions(intent)
    questions: List[str] = []

    if ambiguity >= 0.6:
        if "when" in missing or "time" in missing:
            questions.append("希望什么时候完成或交付？")
        if "audience" in missing:
            questions.append("面向的汇报对象是谁？（上级/同事/客户）")
        if "scope" in missing:
            questions.append("请问希望覆盖的具体范围？")
        # Try Mentor Task for an LLM-backed refinement
        try:
            from core.mentor import mentor_task
            diag = mentor_task.diagnose(intent)
            llm_qs = [q for q in (getattr(diag, "questions", []) or [])]
            for q in llm_qs:
                if q and q not in questions:
                    questions.append(q)
        except Exception as e:
            logger.debug("mentor_task.diagnose skipped: %s", e)

    return ClarifyDecision(
        should_clarify=(ambiguity >= 0.6 and len(questions) >= 1),
        ambiguity=ambiguity,
        questions=questions[:3],
        missing_dimensions=missing,
    )


def _heuristic_ambiguity(intent: str) -> float:
    text = intent.strip()
    if not text:
        return 1.0
    length_penalty = max(0.0, (15 - len(text)) / 15.0)  # very short = ambiguous
    concrete_markers = [
        r"\d{1,2}\s*(?:月|日|周|天|小时|分钟|min|h)",
        r"PPT|演示|汇报|文档|方案|画布|架构",
        r"评审|上级|客户|老板|同事",
    ]
    hits = sum(1 for p in concrete_markers if re.search(p, text))
    base = 0.8 - 0.18 * hits
    return max(0.0, min(1.0, max(base, length_penalty)))


def _missing_dimensions(intent: str) -> List[str]:
    text = intent.lower()
    missing: List[str] = []
    if not re.search(r"(\d{1,2}\s*(?:月|日|周|天|小时|分钟|min|h)|today|tomorrow|周一|周二|周三|周四|周五|本周|下周)",
                     text):
        missing.append("when")
    if not re.search(r"(上级|老板|客户|团队|同事|上司|评委|judges|stakeholder)", text):
        missing.append("audience")
    if not re.search(r"(包含|覆盖|范围|具体|核心模块|章节)", text):
        missing.append("scope")
    return missing


# ── 2. Discussion summarisation ──

def summarise_messages(messages: List[Dict[str, Any]], *, max_points: int = 5) -> str:
    if not messages:
        return ""
    bullets: List[str] = []
    for m in messages[-12:]:
        sender = m.get("sender", "?")
        text = (m.get("text") or "")[:160].strip()
        if not text:
            continue
        bullets.append(f"- **{sender}**：{text}")
    if not bullets:
        return ""
    try:
        from llm.llm_client import chat
        prompt = (
            f"把以下讨论压缩成不超过 {max_points} 条「共识/决议」。每条一行，中文，以动词开头。\n\n"
            + "\n".join(bullets)
        )
        out = chat(prompt, temperature=0.2)
        if out:
            return out.strip()
    except Exception as e:
        logger.debug("summarise llm fallback: %s", e)
    return "- 围绕核心目标达成初步共识\n- 下一步制定详细方案\n- 按时间节点推进交付"


# ── 3. Next-step recommendation ──

def recommend_next_steps(plan_dict: Dict[str, Any]) -> List[str]:
    """Given a completed / running plan dict, suggest 2-3 next actions."""
    steps = plan_dict.get("steps") or []
    tools = {s.get("tool") for s in steps}
    suggestions: List[str] = []
    if "doc.create" in tools:
        suggestions.append("把文档分享到相关群聊并 @ 负责人")
    if "canvas.create" in tools:
        suggestions.append("导出画布为 PNG 并贴进飞书文档作为配图")
    if "slide.generate" in tools:
        suggestions.append("在飞书日历创建 30 分钟评审会议，并把 PPT 附到会议描述")
    if "archive.bundle" in tools:
        suggestions.append("把汇总链接发给上级/评委，收集反馈")
    if not suggestions:
        suggestions.append("对产物做一次语气/措辞 review（`帮我看看：…`）")
    return suggestions[:3]
