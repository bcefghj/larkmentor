"""Module 3: Context Recall – work context recovery after focus sessions."""

import logging

from llm.llm_client import chat
from llm.prompts import CONTEXT_RECOVERY_PROMPT
from memory.user_state import UserState
from memory.context_snapshot import ContextSnapshot, save_snapshot, get_snapshot, clear_snapshot
from utils.time_utils import fmt_time, fmt_duration, now_cst

logger = logging.getLogger("flowguard.recall")


def capture_snapshot(user: UserState, calendar_events: list = None, active_tasks: list = None):
    """Capture current work context when user enters focus mode."""
    snap = ContextSnapshot(
        user_open_id=user.open_id,
        calendar_events=calendar_events or [],
        active_tasks=active_tasks or [],
        last_user_message="",
        custom_context=user.work_context,
    )
    save_snapshot(snap)
    logger.info("Context snapshot captured for user %s", user.open_id)


def generate_recovery(user: UserState, stats: dict) -> str:
    """Generate recovery text using LLM after focus session ends."""
    snap = get_snapshot(user.open_id)
    work_context = snap.summary() if snap else (user.work_context or "未记录")

    p1_list = stats.get("p1_messages", [])
    p1_text = "\n".join(p1_list) if p1_list else "无"

    prompt = CONTEXT_RECOVERY_PROMPT.format(
        start_time=fmt_time(),
        end_time=fmt_time(),
        duration=fmt_duration(stats.get("duration_sec", 0)),
        total_messages=stats.get("total_messages", 0),
        p0_count=stats.get("p0_count", 0),
        p1_count=stats.get("p1_count", 0),
        p2_count=stats.get("p2_count", 0),
        p3_count=stats.get("p3_count", 0),
        p1_messages=p1_text,
        work_context=work_context,
    )

    recovery_text = chat(prompt, temperature=0.4)
    if not recovery_text:
        # Fallback
        parts = [f"专注期间共收到 {stats.get('total_messages', 0)} 条消息。"]
        if p1_list:
            parts.append("待查看消息：")
            for m in p1_list[:5]:
                parts.append(f"  • {m}")
        parts.append("建议先处理待查看消息，再继续之前的工作。")
        recovery_text = "\n".join(parts)

    clear_snapshot(user.open_id)
    return recovery_text
