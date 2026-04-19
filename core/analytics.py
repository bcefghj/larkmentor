"""Module 4: Analytics – interruption cost analysis with smart advice."""

import logging

from memory.user_state import UserState, all_users
from bot.message_sender import send_card
from bot.card_builder import daily_report_card
from utils.time_utils import fmt_duration
from llm.llm_client import chat
from llm.prompts import DAILY_ADVICE_PROMPT

logger = logging.getLogger("flowguard.analytics")


def generate_daily_stats(user: UserState) -> dict:
    return {
        "total": user.daily_interrupt_count,
        "p0": user.daily_p0,
        "p1": user.daily_p1,
        "p2": user.daily_p2,
        "p3": user.daily_p3,
        "focus_seconds": user.daily_focus_seconds,
        "shielded": user.daily_p2 + user.daily_p3,
    }


def _generate_advice(stats: dict) -> str:
    """Use LLM to generate personalized daily advice."""
    if stats["total"] == 0:
        return "今天没有使用专注模式，尝试在高效时段开启保护。"
    try:
        prompt = DAILY_ADVICE_PROMPT.format(
            total=stats["total"], p0=stats["p0"], p1=stats["p1"],
            p2=stats["p2"], p3=stats["p3"],
            focus_duration=fmt_duration(stats["focus_seconds"]),
            shielded=stats["shielded"],
        )
        advice = chat(prompt, temperature=0.5)
        return advice if advice else "尝试在下午 2-4 点设置专注时段，减少深度工作被切碎。"
    except Exception:
        return "尝试在下午 2-4 点设置专注时段，减少深度工作被切碎。"


def send_daily_report_to_user(user: UserState):
    stats = generate_daily_stats(user)
    if stats["total"] == 0 and stats["focus_seconds"] == 0:
        return

    advice = _generate_advice(stats)
    card = daily_report_card(
        total_interrupts=stats["total"],
        p0=stats["p0"], p1=stats["p1"], p2=stats["p2"], p3=stats["p3"],
        focus_seconds=stats["focus_seconds"],
        shielded=stats["shielded"],
        advice=advice,
    )
    send_card(user.open_id, card)
    logger.info("Daily report sent to %s", user.open_id)


def send_all_daily_reports():
    for user in all_users():
        try:
            send_daily_report_to_user(user)
            user.reset_daily()
        except Exception as e:
            logger.error("Failed to send daily report to %s: %s", user.open_id, e)


def get_report_text(user: UserState) -> str:
    stats = generate_daily_stats(user)
    if stats["total"] == 0:
        return "今天还没有收到消息记录。开始专注后，FlowGuard 会自动追踪。"

    focus_dur = fmt_duration(stats["focus_seconds"])
    saved = stats["shielded"] * 2

    return (
        f"**今日报告**\n\n"
        f"总消息数：{stats['total']}\n"
        f"- P0 紧急：{stats['p0']}\n"
        f"- P1 重要：{stats['p1']}\n"
        f"- P2 代回复：{stats['p2']}\n"
        f"- P3 归档：{stats['p3']}\n\n"
        f"深度工作时长：{focus_dur}\n"
        f"FlowGuard 拦截消息：{stats['shielded']} 条\n"
        f"预估节省：约 {saved} 分钟注意力恢复时间"
    )
