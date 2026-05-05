"""Smart Shield message processing – group message triage and focus-mode protection."""

import logging
import os as _os
import time as _time

from bot.card_builder import recovery_card, urgent_alert_card, mentor_proactive_card
from bot.handlers._common import (
    cancel_focus_expiry,
    check_and_send_achievements,
    wm_append,
)
from bot.message_sender import reply_text, send_card, send_text
from config import Config
from core.context_recall import generate_recovery
from core.smart_shield import process_message
from core.smart_shield_v3 import process_message_v3 as _process_message_v3
from core.mentor import proactive_hook as v4_proactive

logger = logging.getLogger("agent_pilot.handler.shield")

_USE_V3_MAIN_CHAIN = _os.getenv("AGENT_PILOT_USE_V3_MAIN_CHAIN", "1") != "0"
_active_process_message = _process_message_v3 if _USE_V3_MAIN_CHAIN else process_message


# ── Proactive mentor suggestions ──


def _resolve_sender_role(sender_name: str, focused_user) -> str:
    """Lightweight role hint: whitelist → 'leader', else 'peer'."""
    try:
        if sender_name and sender_name in (focused_user.whitelist or []):
            return "leader"
    except Exception as e:
        logger.debug("resolve_sender_role lookup failed: %s", e)
    return "peer"


def _maybe_fire_proactive(focused_user, *, sender_name, chat_name, message, level):
    """Try to send a proactive Mentor suggestion. Never raises."""
    if level not in ("P0", "P1"):
        return
    decision = v4_proactive.maybe_suggest(
        focused_user,
        sender_name=sender_name,
        sender_role=_resolve_sender_role(sender_name, focused_user),
        chat_name=chat_name,
        message=message,
        level=level,
    )
    if not decision.fired:
        logger.debug("proactive_skip user=%s reason=%s", focused_user.open_id[-6:], decision.reason)
        return
    try:
        send_card(focused_user.open_id, mentor_proactive_card(decision.suggestion))
        v4_proactive.mark_fired(focused_user)
        try:
            from memory.user_state import _save_all

            _save_all()
        except Exception as e:
            logger.debug("save_all after proactive fire failed: %s", e)
        if decision.risk_warning:
            send_text(focused_user.open_id, f"⚠️ {decision.risk_warning}")
    except Exception as e:
        logger.warning("proactive_send_fail err=%s", e)


# ── Group message handling ──


def handle_group_message(
    sender_open_id: str,
    sender_name: str,
    message_id: str,
    text: str,
    chat_name: str,
):
    """Process a group message for all currently-focusing users.

    Returns True if the message was handled (even if no one was focusing).
    """
    from memory.user_state import all_users

    focusing_users = [u for u in all_users() if u.is_focusing() and u.open_id != sender_open_id]
    if not focusing_users:
        return

    for focused_user in focusing_users:
        result = _active_process_message(
            user=focused_user,
            sender_name=sender_name,
            sender_id=sender_open_id,
            message_id=message_id,
            content=text,
            chat_name=chat_name,
        )
        wm_append(
            focused_user.open_id,
            "message",
            {
                "sender_name": sender_name,
                "chat_name": chat_name,
                "level": result.get("level", "P3"),
                "action": result.get("action", "archive"),
                "content": text[:60],
            },
        )
        wm_append(
            focused_user.open_id,
            "decision",
            {
                "level": result.get("level", "P3"),
                "action": result.get("action", "archive"),
                "score": result.get("score", 0),
                "used_llm": result.get("used_llm", False),
            },
        )
        action = result["action"]
        level = result.get("level", "P3")
        if action == "forward":
            card = urgent_alert_card(sender=sender_name, content=text, chat_name=chat_name)
            send_card(focused_user.open_id, card)
        elif action == "auto_reply":
            reply_body = (result.get("auto_reply_text") or "").strip()
            if reply_body:
                reply_text(message_id, reply_body)
            else:
                logger.info("skip auto_reply: empty body (level=%s)", level)

        try:
            _maybe_fire_proactive(
                focused_user,
                sender_name=sender_name,
                chat_name=chat_name,
                message=text,
                level=level,
            )
        except Exception as e:
            logger.debug("proactive_hook_skipped err=%s", e)

        if result.get("circuit_breaker_triggered"):
            send_text(
                focused_user.open_id,
                f"⚠️ **紧急熔断触发**：在 {Config.CIRCUIT_BREAKER_WINDOW_SEC} 秒内连续收到 "
                f"{Config.CIRCUIT_BREAKER_P0_COUNT} 条 P0 紧急消息。\n"
                f"Agent-Pilot 已自动结束保护模式，请尽快查看。",
            )
            cancel_focus_expiry(focused_user.open_id)
            stats = focused_user.end_focus()
            recovery_text_cb = generate_recovery(focused_user, stats)
            send_card(focused_user.open_id, recovery_card(stats, recovery_text_cb))


def handle_focusing_p2p(
    user,
    sender_name: str,
    sender_open_id: str,
    message_id: str,
    text: str,
):
    """Handle a p2p message when the user is in focus mode (treat like group input)."""
    open_id = user.open_id
    chat_name = f"私聊:{sender_open_id[-6:]}"
    result = _active_process_message(
        user=user,
        sender_name=sender_name,
        sender_id=sender_open_id,
        message_id=message_id,
        content=text,
        chat_name=chat_name,
    )
    wm_append(
        open_id,
        "message",
        {
            "sender_name": sender_name,
            "level": result.get("level", "P3"),
            "action": result.get("action", "archive"),
            "content": text[:60],
        },
    )
    wm_append(
        open_id,
        "decision",
        {
            "level": result.get("level", "P3"),
            "action": result.get("action", "archive"),
            "score": result.get("score", 0),
            "used_llm": result.get("used_llm", False),
        },
    )
    action = result["action"]
    if action == "forward":
        card = urgent_alert_card(sender=sender_name, content=text, chat_name=chat_name)
        send_card(open_id, card)
    elif action == "auto_reply":
        reply_body = (result.get("auto_reply_text") or "").strip()
        if reply_body:
            reply_text(message_id, reply_body)
        else:
            logger.info("skip auto_reply (p2p): empty body")
    if result.get("circuit_breaker_triggered"):
        send_text(
            open_id,
            f"⚠️ **紧急熔断触发**：在 {Config.CIRCUIT_BREAKER_WINDOW_SEC} 秒内连续收到 "
            f"{Config.CIRCUIT_BREAKER_P0_COUNT} 条 P0 紧急消息。\n"
            f"Agent-Pilot 已自动结束保护模式，请尽快查看。",
        )
        cancel_focus_expiry(open_id)
        stats = user.end_focus()
        recovery_text_p2p = generate_recovery(user, stats)
        send_card(open_id, recovery_card(stats, recovery_text_p2p))
