"""Smart Shield – intelligent message triage during focus mode.

Pipeline:
    1. Update sender profile (record incoming).
    2. Run deterministic 6-dimension classifier (fast path).
    3. Optional: invoke LLM as a tie-breaker when score is in ambiguous band
       (THRESHOLD_P1 ± 0.05). Cuts LLM cost ~70%.
    4. Generate auto-reply for P2 (LLM) or use cached template.
    5. Persist pending message + interruption log entry.
    6. Apply emergency circuit breaker check.

Returns the action the caller (event_handler) should take.
"""

import logging
import time
from typing import List

from config import Config
from core.classification_engine import (
    ClassificationResult, classify, explain,
)
from core.classification_engine import _contains_urgent_keyword as _contains_urgent_keyword  # noqa: F401
from core.sender_profile import get_profile, record_incoming
from llm.llm_client import chat_json, chat
from llm.prompts import CLASSIFY_PROMPT, AUTO_REPLY_PROMPT
from memory.user_state import UserState, PendingMessage
from memory.interruption_log import InterruptionEvent, log_event
from utils.time_utils import now_ts
from core.advanced_features import DecisionRecord, record_decision

logger = logging.getLogger("flowguard.shield")


# ── Recent P0 ring buffer for circuit breaker ──
_recent_p0_per_user = {}  # open_id -> [timestamps]


def _check_circuit_breaker(user_open_id: str) -> bool:
    """Return True if too many P0s in window → caller should auto-exit focus."""
    now = now_ts()
    win = Config.CIRCUIT_BREAKER_WINDOW_SEC
    threshold = Config.CIRCUIT_BREAKER_P0_COUNT
    bucket = _recent_p0_per_user.setdefault(user_open_id, [])
    bucket.append(now)
    bucket[:] = [t for t in bucket if now - t < win]
    return len(bucket) >= threshold


def _is_ambiguous(score: float) -> bool:
    """Score within ±0.05 of P0 or P1 boundary → ambiguous, escalate to LLM."""
    return (
        abs(score - Config.THRESHOLD_P0) < 0.05
        or abs(score - Config.THRESHOLD_P1) < 0.05
    )


def _llm_tiebreak(
    user: UserState, sender_name: str, content: str, chat_name: str,
) -> dict:
    """LLM fallback when deterministic score is ambiguous. Returns dict or {}."""
    prompt = CLASSIFY_PROMPT.format(
        user_context=user.work_context or "深度工作中",
        whitelist=", ".join(user.whitelist) if user.whitelist else "无",
        sender=sender_name,
        content=content[:500],
        chat_info=chat_name,
    )
    try:
        result = chat_json(prompt)
        if isinstance(result, dict) and "level" in result:
            return result
    except Exception as e:
        logger.debug("LLM tiebreak error: %s", e)
    return {}


def generate_auto_reply(
    user: UserState, sender_name: str, content: str,
) -> str:
    """LLM-backed auto-reply with safe fallback."""
    try:
        prompt = AUTO_REPLY_PROMPT.format(
            user_context=user.work_context or "专注工作中",
            content=content[:300],
            sender=sender_name,
        )
        reply = chat(prompt, temperature=0.5)
        if not reply:
            reply = "收到，我正在忙，稍后查看回复你。"
    except Exception:
        reply = "收到，我正在忙，稍后查看回复你。"
    if "[LarkMentor代回复]" not in reply:
        reply += " [LarkMentor代回复]"
    return reply


def process_message(
    user: UserState,
    sender_name: str,
    sender_id: str,
    message_id: str,
    content: str,
    chat_name: str,
    chat_type: str = "group",
    member_count: int = None,
) -> dict:
    """Full classification + persistence + action selection pipeline.

    Returns:
        {
            "level": P0/P1/P2/P3,
            "action": forward/queue/auto_reply/archive,
            "auto_reply_text": str,
            "reason": str,
            "score": float,
            "dimensions": {...},
            "circuit_breaker_triggered": bool,
        }
    """
    t_start = time.time()

    profile = record_incoming(sender_id, sender_name)

    result: ClassificationResult = classify(
        user=user, sender_profile=profile, message_text=content,
        chat_type=chat_type, chat_name=chat_name, member_count=member_count,
    )

    # Tie-break with LLM if ambiguous
    if _is_ambiguous(result.score) and not result.short_circuit:
        llm_result = _llm_tiebreak(user, sender_name, content, chat_name)
        if llm_result:
            llm_level = llm_result.get("level", result.level)
            if llm_level in ("P0", "P1", "P2", "P3"):
                result.level = llm_level
                result.reason += f" | LLM 复审: {llm_result.get('reason', '')}"
                result.used_llm = True
                if "auto_reply" in llm_result:
                    result.auto_reply = llm_result["auto_reply"]

    level = result.level
    reason = result.reason

    if level == "P0":
        action = "forward"
        auto_reply_text = ""
    elif level == "P1":
        action = "queue"
        auto_reply_text = ""
    elif level == "P2":
        auto_reply_text = result.auto_reply or generate_auto_reply(user, sender_name, content)
        action = "auto_reply"
    else:
        action = "archive"
        auto_reply_text = ""

    pending = PendingMessage(
        message_id=message_id,
        sender_name=sender_name,
        sender_id=sender_id,
        chat_name=chat_name,
        content=content[:200],
        level=level,
        action=action,
        auto_reply_text=auto_reply_text,
        timestamp=now_ts(),
    )
    user.add_pending(pending)

    log_event(InterruptionEvent(
        timestamp=now_ts(),
        user_open_id=user.open_id,
        sender=sender_name,
        chat_name=chat_name,
        level=level,
        action=action,
        was_focusing=True,
    ))

    cb_triggered = (level == "P0") and _check_circuit_breaker(user.open_id)

    # Audit log (Explainable AI + rollback support)
    decision_id = f"{user.open_id[-6:]}_{message_id[-8:]}"
    record_decision(DecisionRecord(
        decision_id=decision_id,
        timestamp=now_ts(),
        user_open_id=user.open_id,
        sender_id=sender_id,
        sender_name=sender_name,
        message_preview=content[:140],
        classification_level=level,
        classification_score=result.score,
        dimensions=result.dimensions,
        action_taken=action,
        used_llm=result.used_llm,
    ))

    elapsed_ms = int((time.time() - t_start) * 1000)
    logger.info(
        "[Shield] %s → %s (%.2f, %dms) | %s | LLM=%s | CB=%s",
        sender_name, level, result.score, elapsed_ms, reason,
        result.used_llm, cb_triggered,
    )

    return {
        "level": level,
        "action": action,
        "auto_reply_text": auto_reply_text,
        "reason": reason,
        "score": result.score,
        "dimensions": result.dimensions,
        "explanation": explain(result),
        "used_llm": result.used_llm,
        "elapsed_ms": elapsed_ms,
        "circuit_breaker_triggered": cb_triggered,
        "decision_id": decision_id,
    }


# ── Public re-export for backward compatibility ──
def classify_message(user, sender_name, sender_id, content, chat_name):
    """Legacy entry point (kept for backward compatibility with tests)."""
    profile = record_incoming(sender_id, sender_name)
    result = classify(
        user=user, sender_profile=profile, message_text=content,
        chat_type="group", chat_name=chat_name,
    )
    return {
        "level": result.level,
        "reason": result.reason,
        "auto_reply": result.auto_reply,
    }
