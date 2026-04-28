"""Proactive Mentor hook · auto-suggest reply on incoming P0/P1.

Triggered from ``bot/event_handler.py`` whenever a group message lands AND
classifies as P0/P1 AND the user is in ``rookie_mode``. We never reply
automatically -- we **draft 3 versions** and DM the suggestion card to the
user so they pick + send manually.

Throttling (no-spam policy):
- per-user cooldown : ``Config.MENTOR_PROACTIVE_COOLDOWN_SEC`` (default 300s)
- per-user 24h cap  : ``Config.MENTOR_PROACTIVE_DAILY_MAX`` (default 3)
- user opt-out      : ``user.proactive_enabled = False``
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from llm.llm_client import chat_json
from llm.prompts import MENTOR_PROACTIVE_REPLY_PROMPT

from . import knowledge_base as kb

logger = logging.getLogger("flowguard.mentor.proactive")


@dataclass
class ProactiveDecision:
    fired: bool
    reason: str = ""
    suggestion: Optional[dict] = None
    risk_warning: str = ""


def _allowed(user) -> tuple[bool, str]:
    """Check throttling rules. Returns (allowed, reason_if_blocked)."""
    if not getattr(user, "rookie_mode", False):
        return False, "rookie_mode_off"
    if not getattr(user, "proactive_enabled", True):
        return False, "user_disabled"

    try:
        from config import Config

        cooldown = Config.MENTOR_PROACTIVE_COOLDOWN_SEC
        daily_max = Config.MENTOR_PROACTIVE_DAILY_MAX
    except Exception:
        cooldown = 300
        daily_max = 3

    now = int(time.time())
    last_ts = int(getattr(user, "last_proactive_ts", 0) or 0)
    if last_ts and (now - last_ts) < cooldown:
        return False, f"cooldown({now - last_ts}s/{cooldown}s)"

    log = list(getattr(user, "proactive_log_24h", []) or [])
    cutoff = now - 86400
    log = [t for t in log if t >= cutoff]
    user.proactive_log_24h = log  # mutate so save() persists
    if len(log) >= daily_max:
        return False, f"daily_cap({len(log)}/{daily_max})"

    return True, ""


def maybe_suggest(
    user,
    *,
    sender_name: str,
    sender_role: str,
    chat_name: str,
    message: str,
    level: str,
) -> ProactiveDecision:
    """Decide whether to fire and (if yes) build the suggestion payload.

    Caller is responsible for actually sending the card and calling
    :func:`mark_fired` after delivery.
    """
    if level not in ("P0", "P1"):
        return ProactiveDecision(fired=False, reason=f"level_{level}")

    ok, reason = _allowed(user)
    if not ok:
        return ProactiveDecision(fired=False, reason=reason)

    open_id = getattr(user, "open_id", "")
    hits = kb.search(open_id, message[:120]) if open_id else []
    org_context = kb.render_citations(hits) if hits else "（无组织文档可用）"

    user_context = (
        f"focus_mode={getattr(user, 'focus_mode', 'normal')} "
        f"task={getattr(user, 'work_context', '') or 'n/a'}"
    )

    prompt = MENTOR_PROACTIVE_REPLY_PROMPT.format(
        user_context=user_context,
        sender_name=sender_name,
        sender_role=sender_role,
        chat_name=chat_name,
        message=message,
        org_context=org_context,
    )

    try:
        result = chat_json(prompt, temperature=0.2)
    except Exception as e:  # noqa: BLE001
        logger.warning("proactive_llm_fail err=%s", e)
        result = {}

    if not result or "three_versions" not in result:
        # Safe fallback so the user still sees something useful.
        result = {
            "three_versions": {
                "conservative": "收到，我先看一下，稍后回复您。",
                "neutral": (
                    f"收到[{sender_name}]的消息，我先确认一下情况，预计今天内回复您。"
                ),
                "direct": message[:120],
            },
            "risk_warning": "模型暂不可用，已给出兜底模板，请人工复核。",
        }

    # LarkMentor v1 explainable line: tell the user *why* we fired.
    explain_parts = [
        f"分类={level}",
        f"发送方={sender_name}({sender_role})",
    ]
    if hits:
        explain_parts.append(f"匹配 {len(hits)} 条组织文档")
    explain = "，".join(explain_parts)

    return ProactiveDecision(
        fired=True,
        reason="ok",
        suggestion={
            "three_versions": result.get("three_versions", {}),
            "citations": [h.citation_tag() for h in hits],
            "sender_name": sender_name,
            "chat_name": chat_name,
            "level": level,
            "original": message,
            "explain": explain,
        },
        risk_warning=str(result.get("risk_warning", "")),
    )


def mark_fired(user) -> None:
    """Record that we delivered a proactive card. Caller should ``user.save()``."""
    now = int(time.time())
    user.last_proactive_ts = now
    log = list(getattr(user, "proactive_log_24h", []) or [])
    log.append(now)
    cutoff = now - 86400
    user.proactive_log_24h = [t for t in log if t >= cutoff]


def set_enabled(user, enabled: bool) -> None:
    user.proactive_enabled = bool(enabled)
