"""Shared state and utilities for handler submodules."""

import json
import logging
import time as _time

from core.context_recall import generate_recovery
from core.feishu_workspace_init import append_recovery_card, get_workspace
from memory.user_state import ACHIEVEMENT_DEFS, get_user
from bot.card_builder import achievement_card, recovery_card
from bot.message_sender import send_card, send_text

logger = logging.getLogger("agent_pilot.handler")

# ── Mutable global state ──

_scheduler = None


def set_scheduler(sched):
    global _scheduler
    _scheduler = sched


def get_scheduler():
    return _scheduler


# ── v3 FlowMemory bridge ──


def wm_append(open_id: str, kind: str, payload: dict = None):
    """Best-effort append to v3 WorkingMemory. Never raises."""
    try:
        from core.flow_memory.compaction import compact_session
        from core.flow_memory.working import WorkingEvent, WorkingMemory

        wm = WorkingMemory.load(open_id)
        ev = WorkingEvent(ts=int(_time.time()), kind=kind, payload=payload or {})
        spilled = wm.append(ev)
        wm.save()
        if spilled:
            compact_session(spilled, tier="auto")
    except Exception as e:
        logger.debug("wm_append skipped: %s", e)


# ── Achievement check ──


def check_and_send_achievements(open_id: str):
    user = get_user(open_id)
    newly = user.check_achievements()
    for a in newly:
        card = achievement_card(a["name"], a["desc"])
        send_card(open_id, card)


# ── Focus scheduling ──


def auto_end_focus(open_id: str):
    """Called by scheduler when focus timer expires."""
    user = get_user(open_id)
    if not user.is_focusing():
        return
    stats = user.end_focus()
    recovery_text = generate_recovery(user, stats)
    card = recovery_card(stats, recovery_text)
    send_card(open_id, card)
    send_text(open_id, "专注时间到！已自动结束保护模式。")
    try:
        ws = get_workspace(open_id)
        if ws.recovery_doc_token:
            append_recovery_card(open_id, recovery_text)
    except Exception as e:
        logger.debug("append_recovery_card skipped: %s", e)
    check_and_send_achievements(open_id)


def schedule_focus_expiry(open_id: str, duration_sec: int):
    """Schedule auto-end of focus mode."""
    if _scheduler and duration_sec > 0:
        job_id = f"focus_expire_{open_id}"
        try:
            _scheduler.remove_job(job_id)
        except Exception:
            pass  # job may not exist yet, safe to ignore
        from datetime import datetime, timedelta

        run_time = datetime.now() + timedelta(seconds=duration_sec)
        _scheduler.add_job(
            auto_end_focus,
            "date",
            run_date=run_time,
            args=[open_id],
            id=job_id,
            replace_existing=True,
        )
        logger.info("Scheduled focus expiry for %s in %d sec", open_id, duration_sec)


def cancel_focus_expiry(open_id: str):
    if _scheduler:
        try:
            _scheduler.remove_job(f"focus_expire_{open_id}")
        except Exception:
            pass  # job may not exist, safe to ignore


# ── Text extraction ──


def extract_text(message) -> str:
    try:
        content_str = message.content
        content = json.loads(content_str)
        return content.get("text", "").strip()
    except Exception:
        return ""


def resolve_name(open_id: str) -> str:
    """Resolve open_id to display name, fallback to short id."""
    try:
        from utils.feishu_api import resolve_user_name

        return resolve_user_name(open_id)
    except Exception:
        return open_id[:12]
