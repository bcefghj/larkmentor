"""Central event handler – thin router that delegates to handler submodules.

v4: Routes all Feishu messages and card actions.
    - Shield (group message triage) → bot.handlers.shield
    - Mentor (coaching/rookie) → bot.handlers.mentor
    - Pilot (Agent-Pilot task flow) → bot.handlers.pilot
    - Card actions → bot.handlers.card_actions

Public API (backward-compatible):
    - on_message_receive
    - on_card_action
    - set_scheduler
"""

import logging
import threading

import lark_oapi as lark

from core.exceptions import AgentPilotError
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from bot.card_builder import (
    achievements_list_card,
    first_time_welcome_card,
    focus_started_card,
    help_card,
    recovery_card,
    workspace_welcome_card,
)
from bot.handlers import (
    cancel_focus_expiry,
    check_and_send_achievements,
    extract_text,
    handle_focusing_p2p,
    handle_group_message,
    handle_group_pilot,
    handle_mentor_command,
    handle_onboarding_in_progress,
    handle_pilot_command,
    resolve_name,
    schedule_focus_expiry,
    wm_append,
)
from bot.handlers._common import set_scheduler as _set_scheduler
from bot.handlers.card_actions import on_card_action  # noqa: F401 – re-export
from bot.message_sender import reply_text, send_card, send_text
from config import Config
from core.advanced_features import (
    explain_decision,
    list_recent_decisions,
    rollback_decision,
)
from core.analytics import get_report_text
from core.context_recall import capture_snapshot, generate_recovery
from core.feishu_workspace_init import (
    ensure_workspace,
    get_workspace,
    workspace_summary_for_card,
)
from core.flow_detector import get_status_text, parse_command
from memory.user_state import ACHIEVEMENT_DEFS, get_user

logger = logging.getLogger("agent_pilot.handler")


# ── Public API ──


def set_scheduler(sched):
    """Set the APScheduler instance for focus expiry jobs."""
    _set_scheduler(sched)


def on_message_receive(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    """Main entry point for all received messages. Spawns a handler thread."""
    t = threading.Thread(target=_handle_in_thread, args=(data,), daemon=True)
    t.start()


# ── Internal routing ──


def _handle_in_thread(data):
    try:
        _do_handle(data)
    except AgentPilotError as e:
        logger.error("AgentPilotError: %s", e.to_log_dict())
    except Exception as e:
        logger.exception("Error handling message: %s", e)


def _do_handle(data):
    event = data.event
    message = event.message
    sender = event.sender

    chat_type = message.chat_type
    message_id = message.message_id

    sender_id_obj = sender.sender_id
    sender_open_id = sender_id_obj.open_id if sender_id_obj else ""
    sender_type = sender.sender_type

    if sender_type != "user":
        return

    text = extract_text(message)
    if not text:
        return

    sender_name = resolve_name(sender_open_id)

    # ── Group messages ──
    if chat_type != "p2p":
        chat_name = message.chat_id or "unknown_group"
        chat_id = message.chat_id or ""

        # Check for /pilot command in group (doesn't require focus mode)
        _pilot_cmd = parse_command(text)
        if _pilot_cmd.get("command") == "pilot_run":
            handle_group_pilot(
                sender_open_id,
                message_id,
                _pilot_cmd["args"].get("intent", ""),
                chat_name,
            )
            return

        # PilotRouter: detect task intent from natural group conversation
        try:
            from bot.pilot_router import default_pilot_router

            router = default_pilot_router()
            result = router.handle_chat_message(
                sender_open_id=sender_open_id,
                text=text,
                chat_id=chat_id,
                msg_id=message_id,
            )
            if result.handled and result.verdict in ("ready", "clarify"):
                return
        except Exception as e:
            logger.debug("PilotRouter group routing skipped: %s", e)

        # Otherwise, broadcast to all focusing users via Smart Shield
        handle_group_message(sender_open_id, sender_name, message_id, text, chat_name)
        return

    # ── Direct messages (p2p) ──
    open_id = sender_open_id
    user = get_user(open_id)

    cmd = parse_command(text)
    command = cmd["command"]
    args = cmd["args"]

    # Route: Pilot commands
    if handle_pilot_command(command, args, open_id, user, text):
        return

    # Route: Mentor/coaching commands
    if handle_mentor_command(command, args, open_id, user, text):
        return

    # Route: Focus & core commands (kept inline for simplicity)
    if _handle_core_command(command, args, open_id, user, text, message_id):
        return

    # Route: Onboarding in progress (consumes free-text as answer)
    if handle_onboarding_in_progress(open_id, text):
        return

    # Route: Unknown DM in rookie mode
    if user.rookie_mode:
        send_text(
            open_id,
            f"收到消息。发送 `帮助` 查看所有指令。\n\n新人模式已开启，试试 `帮我看看：{text[:20]}` 来审核你的消息。",
        )
        return

    # Route: Not focusing → try PilotRouter for natural intent detection
    if not user.is_focusing():
        try:
            from bot.pilot_router import default_pilot_router

            router = default_pilot_router()
            result = router.handle_chat_message(
                sender_open_id=open_id,
                text=text,
                chat_id=open_id,
                msg_id=message_id,
            )
            if result.handled and result.verdict in ("ready", "clarify", "explicit_ready"):
                return
        except Exception as e:
            logger.debug("PilotRouter DM routing skipped: %s", e)
        send_card(open_id, first_time_welcome_card())
        return

    # Route: User is focusing, treat p2p as group-style input
    handle_focusing_p2p(user, sender_name, sender_open_id, message_id, text)


def _handle_core_command(command: str, args: dict, open_id: str, user, text: str, message_id: str) -> bool:
    """Handle core commands (focus, whitelist, tasks, decisions, workspace). Returns True if handled."""

    if command == "start_focus":
        duration = args.get("duration", 0) or Config.DEFAULT_FOCUS_DURATION
        user.start_focus(duration_min=duration)
        capture_snapshot(user)
        card = focus_started_card(duration)
        send_card(open_id, card)
        schedule_focus_expiry(open_id, duration * 60)
        wm_append(open_id, "focus_start", {"duration_min": duration, "context": user.work_context or ""})
        return True

    if command == "end_focus":
        if not user.is_focusing():
            send_text(open_id, "你当前不在专注模式中。")
            return True
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
                "p0_count": stats.get("p0_count", 0),
            },
        )
        try:
            ws = get_workspace(open_id)
            if ws.recovery_doc_token:
                from core.feishu_workspace_init import append_recovery_card

                append_recovery_card(open_id, recovery_text)
        except Exception as e:
            logger.debug("append_recovery_card skipped: %s", e)
        check_and_send_achievements(open_id)
        return True

    if command == "set_whitelist":
        name = args.get("name", "")
        if name and name not in user.whitelist:
            user.whitelist.append(name)
        send_text(open_id, f"已添加 {name} 到白名单。当前白名单：{', '.join(user.whitelist)}")
        return True

    if command == "remove_whitelist":
        name = args.get("name", "")
        if name in user.whitelist:
            user.whitelist.remove(name)
        send_text(open_id, f"已从白名单移除 {name}。当前白名单：{', '.join(user.whitelist) or '无'}")
        return True

    if command == "list_whitelist":
        wl = ", ".join(user.whitelist) if user.whitelist else "无"
        send_text(open_id, f"当前白名单：{wl}")
        return True

    if command == "show_status":
        send_text(open_id, get_status_text(user))
        return True

    if command == "daily_report":
        report = get_report_text(user)
        send_text(open_id, report)
        return True

    if command == "help":
        card = help_card()
        send_card(open_id, card)
        return True

    if command == "set_context":
        user.work_context = args.get("context", "")
        send_text(open_id, f"已记录工作上下文：{user.work_context}")
        return True

    # Multi-task
    if command == "add_task":
        result = user.add_task(args.get("name", ""))
        send_text(open_id, result)
        return True

    if command == "switch_task":
        result = user.switch_task(args.get("name", ""))
        send_text(open_id, result)
        return True

    if command == "remove_task":
        result = user.remove_task(args.get("name", ""))
        send_text(open_id, result)
        return True

    if command == "list_tasks":
        send_text(open_id, user.task_list_text())
        return True

    # Achievements
    if command == "show_achievements":
        card = achievements_list_card(user.unlocked_achievements, ACHIEVEMENT_DEFS)
        send_card(open_id, card)
        return True

    # Workspace
    if command == "demo_workspace":
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
            logger.exception("Workspace provisioning error: %s", e)
            send_text(open_id, f"工作台开通失败：{e}\n\n请联系管理员检查应用权限（bitable:app / docx:document）。")
        return True

    if command == "show_workspace":
        ws = get_workspace(open_id)
        if not ws.is_complete():
            send_text(open_id, "你还没有工作台。发送 `演示工作台` 立即创建。")
            return True
        summary = workspace_summary_for_card(ws)
        send_card(
            open_id,
            workspace_welcome_card(
                bitable_url=summary["bitable_url"],
                onboarding_url=summary["onboarding_url"],
                recovery_url=summary["recovery_url"],
                complete=True,
            ),
        )
        return True

    # Decisions
    if command == "list_decisions":
        decisions = list_recent_decisions(open_id, limit=8)
        if not decisions:
            send_text(open_id, "尚无决策记录。专注模式中收到群消息后会自动记录。")
            return True
        lines = ["**最近 8 条决策（输入 `为什么 决策ID` 查看详情）：**\n"]
        for d in decisions:
            tag = "↩️" if d.rolled_back else " "
            lines.append(
                f"{tag} `{d.decision_id}` [{d.classification_level} {d.classification_score:.2f}] "
                f"{d.sender_name}: {d.message_preview[:30]}"
            )
        send_text(open_id, "\n".join(lines))
        return True

    if command == "explain_decision":
        decision_id = args.get("id", "")
        decisions = list_recent_decisions(open_id, limit=200)
        target = next((d for d in decisions if d.decision_id == decision_id), None)
        if not target:
            send_text(open_id, f"未找到决策 `{decision_id}`。请先发 `最近决策` 查看可用 ID。")
            return True
        send_text(open_id, explain_decision(target))
        return True

    if command == "rollback_decision":
        decision_id = args.get("id", "")
        new_level = args.get("level", "")
        rec = rollback_decision(decision_id, new_level, "user_corrected_manually")
        if not rec:
            send_text(open_id, f"未找到决策 `{decision_id}`。")
            return True
        send_text(
            open_id,
            f"已将决策 `{decision_id}` 从 {rec.classification_level} 回滚为 {new_level}。\n\n"
            f"你的反馈已写入发送者画像，下次类似消息会更准确。",
        )
        return True

    if command == "rollback_recent":
        decisions = list_recent_decisions(open_id, limit=1)
        if not decisions:
            send_text(open_id, "暂无可撤回的决策。")
            return True
        d = decisions[0]
        rec = rollback_decision(d.decision_id, "P0", "user_quick_rollback")
        if rec:
            send_text(open_id, f"已撤回最近一条决策 `{d.decision_id}`（{d.classification_level} → P0）。")
        else:
            send_text(open_id, "撤回失败，请用 `最近决策` 查看后手动回滚。")
        return True

    return False
