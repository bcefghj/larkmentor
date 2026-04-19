"""Mentor Router · light supervisor.

We avoid LangGraph / CrewAI on purpose -- the v3 Bot is a single-file
event handler and forcing a framework would shred the architecture.
Instead this module exposes one ``route()`` call that decides which
specialist (writing / task / weekly) should handle a given user input.

The router uses a fast keyword short-circuit first (< 1 ms, no LLM cost),
then falls back to a single LLM classification for ambiguous cases.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from llm.llm_client import chat_json
from llm.prompts import MENTOR_ROUTER_PROMPT

logger = logging.getLogger("flowguard.mentor.router")


# Order matters: more specific keywords first.
_KEYWORDS = [
    ("weekly", ["周报", "月报", "复盘", "weekly", "monthly", "wrapped"]),
    ("task", ["任务", "需求", "deadline", "ddl", "交付", "拆解", "需求方"]),
    ("writing", [
        "怎么回", "怎么写", "怎么说", "改一下", "润色",
        "帮我看", "代我回", "建议回复", "草拟",
    ]),
]


@dataclass
class RouteDecision:
    role: str          # "writing" | "task" | "weekly" | "chitchat"
    confidence: float  # 0-1
    method: str        # "keyword" | "llm" | "default"
    why: str = ""


def _short_circuit(text: str) -> Optional[RouteDecision]:
    if not text:
        return None
    low = text.lower()
    for role, kws in _KEYWORDS:
        for kw in kws:
            if kw.lower() in low:
                return RouteDecision(
                    role=role, confidence=0.85, method="keyword",
                    why=f"matched '{kw}'",
                )
    return None


def route(user_input: str, *, allow_llm: bool = True) -> RouteDecision:
    """Decide which mentor should handle this input.

    Always returns a decision; never raises.
    """
    if not user_input or not user_input.strip():
        return RouteDecision(role="chitchat", confidence=1.0, method="default", why="empty")

    sc = _short_circuit(user_input)
    if sc is not None:
        return sc

    if not allow_llm:
        return RouteDecision(role="writing", confidence=0.4, method="default", why="no_keyword")

    try:
        prompt = MENTOR_ROUTER_PROMPT.format(user_input=user_input[:500])
        result = chat_json(prompt, temperature=0.0)
    except Exception as e:  # noqa: BLE001
        logger.warning("router_llm_fail err=%s", e)
        result = {}

    role = (result.get("role") or "writing").lower()
    if role not in {"writing", "task", "weekly", "chitchat"}:
        role = "writing"
    try:
        conf = float(result.get("confidence", 0.5))
    except Exception:
        conf = 0.5
    return RouteDecision(
        role=role, confidence=conf, method="llm",
        why=str(result.get("why", ""))[:60],
    )
