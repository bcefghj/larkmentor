"""Card callback handling – button clicks from Feishu interactive cards."""

import logging
import threading
import time as _time

from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from bot.card_builder import (
    focus_started_card,
    help_card,
    mentor_weekly_card,
    recovery_card,
    workspace_welcome_card,
)
from bot.handlers._common import (
    cancel_focus_expiry,
    check_and_send_achievements,
    schedule_focus_expiry,
    wm_append,
)
from bot.message_sender import send_card, send_text
from config import Config
from core.analytics import get_report_text
from core.context_recall import capture_snapshot, generate_recovery
from core.feishu_workspace_init import ensure_workspace, workspace_summary_for_card
from core.flow_detector import get_status_text
from core.mentor import (
    mentor_review as v4_weekly,
    proactive_hook as v4_proactive,
)
from memory.user_state import get_user

logger = logging.getLogger("agent_pilot.handler.card")


def on_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    """Handle card button clicks. Must return within 3 seconds."""
    try:
        action_value = data.event.action.value or {}
        action = action_value.get("action", "")
        open_id = data.event.operator.open_id

        t = threading.Thread(
            target=_handle_card_action_async,
            args=(open_id, action),
            daemon=True,
        )
        t.start()

        toast_map = {
            "end_focus": "正在结束专注...",
            "start_focus": "正在开始专注...",
            "show_status": "正在查询状态...",
            "daily_report": "正在生成报告...",
            "demo_workspace": "正在创建工作台...",
            "help": "正在加载帮助...",
        }
        toast_text = toast_map.get(action, "处理中...")
        return P2CardActionTriggerResponse({"toast": {"type": "info", "content": toast_text}})
    except Exception as e:
        logger.exception("Card action error: %s", e)
        return P2CardActionTriggerResponse({"toast": {"type": "error", "content": "处理失败，请重试"}})


def _handle_card_action_async(open_id: str, action: str):
    """Process card action in background thread."""
    try:
        user = get_user(open_id)

        if action == "end_focus":
            if not user.is_focusing():
                send_text(open_id, "你当前不在专注模式中。")
                return
            cancel_focus_expiry(open_id)
            stats = user.end_focus()
            recovery_text = generate_recovery(user, stats)
            card = recovery_card(stats, recovery_text)
            send_card(open_id, card)
            wm_append(
                open_id,
                "focus_end",
                {
                    "duration_min": stats.get("duration_sec", 0) // 60,
                    "total_messages": stats.get("total_messages", 0),
                },
            )
            check_and_send_achievements(open_id)

        elif action == "start_focus":
            duration = Config.DEFAULT_FOCUS_DURATION
            user.start_focus(duration_min=duration)
            capture_snapshot(user)
            card = focus_started_card(duration)
            send_card(open_id, card)
            schedule_focus_expiry(open_id, duration * 60)
            wm_append(open_id, "focus_start", {"duration_min": duration})

        elif action == "show_status":
            send_text(open_id, get_status_text(user))

        elif action == "daily_report":
            report = get_report_text(user)
            send_text(open_id, report)

        elif action == "demo_workspace":
            send_text(open_id, "正在为你自动开通飞书工作台（多维表格 + 文档），约 5-10 秒...")
            try:
                ws = ensure_workspace(open_id, force=False)
                summary = workspace_summary_for_card(ws)
                send_card(
                    open_id,
                    workspace_welcome_card(
                        bitable_url=summary["bitable_url"],
                        onboarding_url=summary["onboarding_url"],
                        recovery_url=summary["recovery_url"],
                        complete=summary["complete"],
                    ),
                )
            except Exception as e:
                logger.exception("Workspace provisioning error (card): %s", e)
                send_text(open_id, f"工作台开通失败：{e}\n\n请联系管理员检查应用权限（bitable:app / docx:document）。")

        elif action == "help":
            send_card(open_id, help_card())

        # ── v4 Mentor card actions ──
        elif action in ("mentor_pick", "mentor_pick_proactive"):
            send_text(open_id, "✅ 已采纳，请直接复制上面那一版回复发出去。Mentor 不会替你发送。")
        elif action == "mentor_dismiss_proactive":
            send_text(open_id, "🔕 已忽略本次主动建议。下次仍会在 P0/P1 时尝试。")
        elif action == "mentor_clarified":
            send_text(open_id, "好的，等对方回答后再发 `任务确认：` 让我重新评估。")
        elif action == "mentor_skip_clarify":
            send_text(open_id, "已跳过澄清。可直接 `任务确认：xxx` 让我给出理解+计划。")
        elif action == "mentor_start_task":
            send_text(open_id, "💪 开工！需要时随时 `@Mentor xxx`。")
        elif action == "mentor_back_to_clarify":
            send_text(open_id, "好的，把任务原文重新发我，或追加更多细节。")
        elif action == "mentor_append_growth":
            send_text(open_id, "📓 已追加到《我的新手成长记录》Docx。")
        elif action == "mentor_regen_weekly":
            try:
                wk = v4_weekly.draft(open_id)
                send_card(open_id, mentor_weekly_card(wk.to_dict()))
            except Exception as e:
                send_text(open_id, f"重新生成失败：{e}")
        elif action == "mentor_show_growth_week":
            from core.mentor.growth_doc import load_entries

            week = load_entries(open_id, since_ts=int(_time.time()) - 7 * 86400)
            if not week:
                send_text(open_id, "本周暂无 Mentor 出手记录。")
            else:
                lines = [f"📓 **本周 {len(week)} 条 Mentor 记录**\n"]
                for e in week[-10:]:
                    ts_str = _time.strftime("%m-%d %H:%M", _time.localtime(e.ts))
                    lines.append(f"- [{ts_str}] [{e.kind}] {e.original[:40]} → {e.improved[:40]}")
                send_text(open_id, "\n".join(lines))
        elif action == "mentor_proactive_off":
            v4_proactive.set_enabled(user, False)
            send_text(open_id, "🔕 已关闭 Mentor 主动建议。")
        elif action == "mentor_proactive_on":
            v4_proactive.set_enabled(user, True)
            send_text(open_id, "✅ 已开启 Mentor 主动建议。")

        else:
            logger.warning("Unknown card action: %s", action)

    except Exception as e:
        logger.exception("Card action async error: %s", e)
