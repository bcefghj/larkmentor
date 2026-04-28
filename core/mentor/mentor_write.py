"""Writing mentor.

Replaces v3 ``rookie_buddy.review_message`` with:
- NVC (Non-Violent Communication) 4-segment diagnosis
- 3-version rewrite (conservative / neutral / direct)
- Org-style RAG context with citations
- Structured JSON output ready for the v4 ``mentor_review_card``

Public helpers used by ``core.recovery_card`` (LarkMentor v2 双线交点)：

* ``review(open_id, message, *, recipient)`` → ``WritingReview``
* ``draft_three_tones(user_open_id, sender_name, content)`` →
  ``[(tone, label, text, citation), ...]`` 适配 Recovery Card 卡片渲染
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Tuple

from llm.llm_client import chat_json
from llm.prompts import MENTOR_WRITE_PROMPT

from . import knowledge_base as kb

logger = logging.getLogger("flowguard.mentor.write")


@dataclass
class WritingReview:
    risk_level: str = "low"
    risk_description: str = ""
    nvc_diagnosis: dict = field(default_factory=dict)
    three_versions: dict = field(default_factory=lambda: {
        "conservative": "", "neutral": "", "direct": "",
    })
    explanation: str = ""
    uses_org_style: bool = False
    citations: List[str] = field(default_factory=list)
    fallback: bool = False

    def to_dict(self) -> dict:
        return {
            "risk_level": self.risk_level,
            "risk_description": self.risk_description,
            "nvc_diagnosis": self.nvc_diagnosis,
            "three_versions": self.three_versions,
            "explanation": self.explanation,
            "uses_org_style": self.uses_org_style,
            "citations": self.citations,
            "fallback": self.fallback,
        }


def _safe_fallback(message: str) -> WritingReview:
    return WritingReview(
        risk_level="low",
        risk_description="",
        nvc_diagnosis={
            "observation": "（LLM 不可用，跳过 NVC 诊断）",
            "feeling": "", "need": "", "request": "",
        },
        three_versions={
            "conservative": "收到，我稍后处理后回复您。",
            "neutral": f"收到，我先看一下，预计今天内给您反馈。原文：{message[:60]}",
            "direct": message,  # 直接版兜底就是原文
        },
        explanation="模型暂时不可用，已给出兜底模板，请人工复核。",
        uses_org_style=False,
        citations=[],
        fallback=True,
    )


_RECIPIENT_HINTS = {
    "boss": "对老板/上级（强敬语，先确认收到，避免长解释）",
    "peer": "对同事（平等语气，简洁直接）",
    "report": "对下属（鼓励 + 明确目标，不要施压）",
}


def _normalise_recipient(recipient: str) -> str:
    """Map shorthand to a richer hint phrase the LLM can use."""
    r = (recipient or "").strip().lower()
    if r in ("boss", "leader", "上级", "老板"):
        return _RECIPIENT_HINTS["boss"]
    if r in ("peer", "colleague", "同事"):
        return _RECIPIENT_HINTS["peer"]
    if r in ("report", "subordinate", "下属"):
        return _RECIPIENT_HINTS["report"]
    return recipient or "同事/上级"


def review(
    open_id: str,
    message: str,
    *,
    recipient: str = "同事/上级",
) -> WritingReview:
    """Mentor the user on a draft message.

    Always returns a ``WritingReview``; never raises.

    ``recipient`` accepts shorthand (``boss`` / ``peer`` / ``report``) which is
    expanded into a richer hint phrase before reaching the LLM. This realises
    the LarkMentor v1 "3 档语气" feature.
    """
    if not message or not message.strip():
        return WritingReview(
            risk_level="low",
            explanation="原文为空，无需改写。",
        )

    hits = kb.search(open_id, message[:120])
    org_context = kb.render_citations(hits) if hits else "（无组织文档可用）"
    citations = [h.citation_tag() for h in hits]

    prompt = MENTOR_WRITE_PROMPT.format(
        org_context=org_context,
        message=message,
        recipient=_normalise_recipient(recipient),
    )

    try:
        result = chat_json(prompt, temperature=0.2)
    except Exception as e:  # noqa: BLE001
        logger.warning("writing_llm_fail err=%s", e)
        result = {}

    if not result or "three_versions" not in result:
        return _safe_fallback(message)

    versions = result.get("three_versions") or {}
    nvc = result.get("nvc_diagnosis") or {}

    return WritingReview(
        risk_level=str(result.get("risk_level", "low")),
        risk_description=str(result.get("risk_description", "")),
        nvc_diagnosis={
            "observation": str(nvc.get("observation", "")),
            "feeling": str(nvc.get("feeling", "")),
            "need": str(nvc.get("need", "")),
            "request": str(nvc.get("request", "")),
        },
        three_versions={
            "conservative": str(versions.get("conservative", message)),
            "neutral": str(versions.get("neutral", message)),
            "direct": str(versions.get("direct", message)),
        },
        explanation=str(result.get("explanation", "")),
        uses_org_style=bool(result.get("uses_org_style", False)) and bool(hits),
        citations=citations,
        fallback=False,
    )


# ── Recovery Card adapter (LarkMentor v2 双线交点) ────────────────


_TONE_LABELS = [
    ("conservative", "保守"),
    ("neutral", "中性"),
    ("direct", "直接"),
]


def draft_three_tones(
    user_open_id: str,
    sender_name: str,
    content: str,
) -> List[Tuple[str, str, str, str]]:
    """Generate 3 tone versions and return as flat tuples.

    Adapter on top of ``review()`` for the ``recovery_card`` module so it
    doesn't have to know about ``WritingReview``. Always returns 3 tuples;
    if everything fails, returns 3 fallback templates rather than raising.

    Returns: list of ``(tone, label, text, citation)``
    """

    try:
        wr = review(user_open_id, content, recipient="peer")
    except Exception as e:
        logger.info("draft_three_tones review failed: %s", e)
        wr = _safe_fallback(content)

    versions = wr.three_versions or {}
    citation = wr.citations[0] if wr.citations else ""

    out: List[Tuple[str, str, str, str]] = []
    for tone, label in _TONE_LABELS:
        text = str(versions.get(tone) or "").strip()
        if not text:
            text = {
                "conservative": f"收到，我刚回到工位，看一下后立刻回复 {sender_name}。",
                "neutral": f"{sender_name}，我刚结束专注，今天稍晚给你回复，可以吗？",
                "direct": "已收到。今天稍晚回复。",
            }[tone]
        out.append((tone, label, text, citation))
    return out
