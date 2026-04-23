"""Central event handler – routes all Feishu messages and card actions.

v4: 新增 bot/handlers_v4.py 统一入口路由（Agent-Pilot + 多 agent + Named Agents）。
    v4 命令/Agent Pilot 场景会由 v4 handlers 处理；Shield/Mentor legacy 路径保留。
"""

import json
import logging
import threading
import time as _time

# v4 统一入口（new!）
_USE_V4_HANDLERS = True  # feature flag; set False to disable v4 routing
try:
    from bot.handlers_v4 import handle_message as _v4_handle_message, classify_intent as _v4_classify
except Exception as _e:
    _USE_V4_HANDLERS = False
    _v4_handle_message = None  # type: ignore
    _v4_classify = None  # type: ignore

import lark_oapi as lark
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from memory.user_state import (
    get_user, add_org_doc, ACHIEVEMENT_DEFS,
)
from core.flow_detector import parse_command, get_status_text
from core.smart_shield import process_message  # legacy v1 compat
from core.smart_shield_v3 import process_message_v3 as _process_message_v3
import os as _os
_USE_V3_MAIN_CHAIN = _os.getenv("LARKMENTOR_USE_V3_MAIN_CHAIN", "1") != "0"
_active_process_message = _process_message_v3 if _USE_V3_MAIN_CHAIN else process_message
from core.context_recall import capture_snapshot, generate_recovery
from core.analytics import get_report_text, send_daily_report_to_user
from core.rookie_buddy import review_message, generate_task_confirmation, generate_weekly_report  # legacy v3 compat
from core.mentor import (
    mentor_write as v4_write,
    mentor_task as v4_task,
    mentor_review as v4_weekly,
    mentor_router as v4_router,
    knowledge_base as v4_kb,
    proactive_hook as v4_proactive,
    growth_doc as v4_growth,
    mentor_onboard,
)
from bot.message_sender import send_text, reply_text, send_card, reply_card
from bot.card_builder import (
    focus_started_card,
    urgent_alert_card,
    batch_reminder_card,
    recovery_card,
    help_card,
    rookie_review_card,
    achievement_card,
    achievements_list_card,
    workspace_welcome_card,
    first_time_welcome_card,
    mentor_review_card,
    mentor_clarify_card,
    mentor_weekly_card,
    mentor_growth_card,
    mentor_proactive_card,
)
from core.feishu_workspace_init import (
    ensure_workspace, workspace_summary_for_card, append_recovery_card,
    get_workspace,
)
from core.advanced_features import (
    list_recent_decisions, rollback_decision, explain_decision,
)
from config import Config

logger = logging.getLogger("flowguard.handler")


# ── v3 FlowMemory bridge ──

def _wm_append(open_id: str, kind: str, payload: dict = None):
    """Best-effort append to v3 WorkingMemory. Never raises."""
    try:
        from core.flow_memory.working import WorkingMemory, WorkingEvent
        from core.flow_memory.compaction import compact_session
        wm = WorkingMemory.load(open_id)
        ev = WorkingEvent(ts=int(_time.time()), kind=kind, payload=payload or {})
        spilled = wm.append(ev)
        wm.save()
        if spilled:
            compact_session(spilled, tier="auto")
    except Exception as e:
        logger.debug("wm_append skipped: %s", e)

_scheduler = None


def set_scheduler(sched):
    global _scheduler
    _scheduler = sched


def _pilot_help_text() -> str:
    return (
        "🚀 **LarkMentor Agent-Pilot 使用指南**\n\n"
        "**核心指令**：\n"
        "  `/pilot <你的需求>` - 自动生成文档/PPT/画布\n\n"
        "**快速示例**：\n"
        "  • `/pilot 生成产品方案文档`\n"
        "  • `/pilot 画一张系统架构图`\n"
        "  • `/pilot 制作评审演示PPT`\n"
        "  • `/pilot 把本周讨论整理成方案+图+PPT` ⭐\n\n"
        "**执行流程**：\n"
        "  1️⃣ Agent 智能规划（拆分为多个步骤）\n"
        "  2️⃣ 并行生成文档/画布/PPT\n"
        "  3️⃣ 实时同步到所有设备\n"
        "  4️⃣ 生成飞书分享链接\n\n"
        "**预计时间**：40-60秒完成所有产物\n\n"
        "**其他指令**：\n"
        "  • `我的飞行员` / `/pilot list` - 查看历史\n"
        "  • `/plan <意图>` - 只规划不执行（Plan Mode）\n"
        "  • `/context` - 查看 Agent 上下文快照\n"
        "  • `/skills` - 查看挂载的 Skills（22 官方 + 3 自研）\n"
        "  • `/mcp` - 查看已连接的 MCP 服务器\n"
        "  • `状态` - 查看当前执行状态\n\n"
        "**在线Dashboard**：\n"
        "  http://118.178.242.26/dashboard/pilot\n\n"
        "**详细文档**：\n"
        "  https://github.com/bcefghj/larkmentor\n\n"
        "💡 提示：需求描述越具体，生成效果越好！"
    )


# ── v4 Mentor: proactive helper ──

def _resolve_sender_role(sender_name: str, focused_user) -> str:
    """Lightweight role hint: whitelist → 'leader', else 'peer'.

    Used by the proactive prompt; caller is robust to bad values.
    """
    try:
        if sender_name and sender_name in (focused_user.whitelist or []):
            return "leader"
    except Exception:
        pass
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
            from memory.user_state import _save_all  # type: ignore

            _save_all()
        except Exception:
            pass
        if decision.risk_warning:
            send_text(focused_user.open_id, f"⚠️ {decision.risk_warning}")
    except Exception as e:
        logger.warning("proactive_send_fail err=%s", e)


def _extract_text(message) -> str:
    try:
        content_str = message.content
        content = json.loads(content_str)
        return content.get("text", "").strip()
    except Exception:
        return ""


def _resolve_name(open_id: str) -> str:
    """Resolve open_id to display name, fallback to short id."""
    try:
        from utils.feishu_api import resolve_user_name
        return resolve_user_name(open_id)
    except Exception:
        return open_id[:12]


def _check_and_send_achievements(open_id: str):
    user = get_user(open_id)
    newly = user.check_achievements()
    for a in newly:
        card = achievement_card(a["name"], a["desc"])
        send_card(open_id, card)


def _auto_end_focus(open_id: str):
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
    except Exception:
        pass
    _check_and_send_achievements(open_id)


def _schedule_focus_expiry(open_id: str, duration_sec: int):
    """Schedule auto-end of focus mode."""
    if _scheduler and duration_sec > 0:
        job_id = f"focus_expire_{open_id}"
        # Remove existing job if any
        try:
            _scheduler.remove_job(job_id)
        except Exception:
            pass
        from datetime import datetime, timedelta
        run_time = datetime.now() + timedelta(seconds=duration_sec)
        _scheduler.add_job(
            _auto_end_focus, "date", run_date=run_time,
            args=[open_id], id=job_id, replace_existing=True,
        )
        logger.info("Scheduled focus expiry for %s in %d sec", open_id, duration_sec)


def _cancel_focus_expiry(open_id: str):
    if _scheduler:
        try:
            _scheduler.remove_job(f"focus_expire_{open_id}")
        except Exception:
            pass


# ── Card action callback ──

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
        return P2CardActionTriggerResponse({
            "toast": {"type": "info", "content": toast_text}
        })
    except Exception as e:
        logger.exception("Card action error: %s", e)
        return P2CardActionTriggerResponse({
            "toast": {"type": "error", "content": "处理失败，请重试"}
        })


def _handle_card_action_async(open_id: str, action: str):
    """Process card action in background thread."""
    try:
        user = get_user(open_id)

        if action == "end_focus":
            if not user.is_focusing():
                send_text(open_id, "你当前不在专注模式中。")
                return
            _cancel_focus_expiry(open_id)
            stats = user.end_focus()
            recovery_text = generate_recovery(user, stats)
            card = recovery_card(stats, recovery_text)
            send_card(open_id, card)
            _wm_append(open_id, "focus_end", {
                "duration_min": stats.get("duration_sec", 0) // 60,
                "total_messages": stats.get("total_messages", 0),
            })
            _check_and_send_achievements(open_id)

        elif action == "start_focus":
            duration = Config.DEFAULT_FOCUS_DURATION
            user.start_focus(duration_min=duration)
            capture_snapshot(user)
            card = focus_started_card(duration)
            send_card(open_id, card)
            _schedule_focus_expiry(open_id, duration * 60)
            _wm_append(open_id, "focus_start", {"duration_min": duration})

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
                send_card(open_id, workspace_welcome_card(
                    bitable_url=summary["bitable_url"],
                    onboarding_url=summary["onboarding_url"],
                    recovery_url=summary["recovery_url"],
                    complete=summary["complete"],
                ))
            except Exception as e:
                logger.exception("Workspace provisioning error (card): %s", e)
                send_text(open_id, f"工作台开通失败：{e}\n\n请联系管理员检查应用权限（bitable:app / docx:document）。")

        elif action == "help":
            send_card(open_id, help_card())

        # ── v4 Mentor card actions ──
        elif action == "mentor_pick" or action == "mentor_pick_proactive":
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


# ── Message handler ──

def _handle_in_thread(data):
    try:
        _do_handle(data)
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

    text = _extract_text(message)
    if not text:
        return

    sender_name = _resolve_name(sender_open_id)

    # ── Group messages: broadcast to ALL currently focusing users ──
    if chat_type != "p2p":
        chat_name = message.chat_id or "unknown_group"

        # v2 Agent-Pilot: group @bot /pilot <intent> entry (does NOT require focus mode)
        _pilot_cmd = parse_command(text)
        if _pilot_cmd.get("command") == "pilot_run":
            try:
                from core.agent_pilot.service import launch as _pilot_launch
                plan = _pilot_launch(
                    _pilot_cmd["args"].get("intent", ""),
                    user_open_id=sender_open_id,
                    meta={"source": "feishu_group", "chat_id": message.chat_id,
                          "chat_name": chat_name},
                    async_run=True,
                )
                reply_text(
                    message_id,
                    f"🛫 Agent-Pilot 已启动 `{plan.plan_id}`（共 {len(plan.steps)} 步）。"
                    f"完成后将在此群回帖汇总。\n实时进度：http://118.178.242.26/dashboard/pilot?plan_id={plan.plan_id}",
                )
            except Exception as e:
                logger.exception("group pilot_run error: %s", e)
                reply_text(message_id, f"Agent-Pilot 启动失败：{e}")
            return

        from memory.user_state import all_users
        focusing_users = [u for u in all_users() if u.is_focusing() and u.open_id != sender_open_id]
        if not focusing_users:
            # Nobody is focusing, nothing to do for group messages
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
            _wm_append(focused_user.open_id, "message", {
                "sender_name": sender_name, "chat_name": chat_name,
                "level": result.get("level", "P3"), "action": result.get("action", "archive"),
                "content": text[:60],
            })
            _wm_append(focused_user.open_id, "decision", {
                "level": result.get("level", "P3"), "action": result.get("action", "archive"),
                "score": result.get("score", 0), "used_llm": result.get("used_llm", False),
            })
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

            # ── v4: Mentor proactive suggestion on P0/P1 ──
            try:
                _maybe_fire_proactive(
                    focused_user, sender_name=sender_name,
                    chat_name=chat_name, message=text, level=level,
                )
            except Exception as e:
                logger.debug("proactive_hook_skipped err=%s", e)

            if result.get("circuit_breaker_triggered"):
                send_text(
                    focused_user.open_id,
                    f"⚠️ **紧急熔断触发**：在 {Config.CIRCUIT_BREAKER_WINDOW_SEC} 秒内连续收到 "
                    f"{Config.CIRCUIT_BREAKER_P0_COUNT} 条 P0 紧急消息。\n"
                    f"LarkMentor 已自动结束保护模式，请尽快查看。"
                )
                _cancel_focus_expiry(focused_user.open_id)
                stats = focused_user.end_focus()
                recovery_text_cb = generate_recovery(focused_user, stats)
                send_card(focused_user.open_id, recovery_card(stats, recovery_text_cb))
        return

    # ── Direct commands (p2p) ──
    # In p2p, the sender IS the user being served
    open_id = sender_open_id
    user = get_user(open_id)

    cmd = parse_command(text)
    command = cmd["command"]
    args = cmd["args"]

    if command == "start_focus":
            duration = args.get("duration", 0) or Config.DEFAULT_FOCUS_DURATION
            user.start_focus(duration_min=duration)
            capture_snapshot(user)
            card = focus_started_card(duration)
            send_card(open_id, card)
            _schedule_focus_expiry(open_id, duration * 60)
            _wm_append(open_id, "focus_start", {"duration_min": duration, "context": user.work_context or ""})
            return

    if command == "end_focus":
            if not user.is_focusing():
                send_text(open_id, "你当前不在专注模式中。")
                return
            _cancel_focus_expiry(open_id)
            stats = user.end_focus()
            recovery_text = generate_recovery(user, stats)
            card = recovery_card(stats, recovery_text)
            send_card(open_id, card)
            _wm_append(open_id, "focus_end", {
                "duration_min": stats.get("duration_sec", 0) // 60,
                "total_messages": stats.get("total_messages", 0),
                "p0_count": stats.get("p0_count", 0),
            })
            try:
                ws = get_workspace(open_id)
                if ws.recovery_doc_token:
                    append_recovery_card(open_id, recovery_text)
            except Exception:
                pass
            _check_and_send_achievements(open_id)
            return

    if command == "set_whitelist":
            name = args.get("name", "")
            if name and name not in user.whitelist:
                user.whitelist.append(name)
            send_text(open_id, f"已添加 {name} 到白名单。当前白名单：{', '.join(user.whitelist)}")
            return

    if command == "remove_whitelist":
            name = args.get("name", "")
            if name in user.whitelist:
                user.whitelist.remove(name)
            send_text(open_id, f"已从白名单移除 {name}。当前白名单：{', '.join(user.whitelist) or '无'}")
            return

    if command == "list_whitelist":
            wl = ", ".join(user.whitelist) if user.whitelist else "无"
            send_text(open_id, f"当前白名单：{wl}")
            return

    if command == "show_status":
            send_text(open_id, get_status_text(user))
            return

    if command == "daily_report":
            report = get_report_text(user)
            send_text(open_id, report)
            return

    if command == "help":
            card = help_card()
            send_card(open_id, card)
            return

    if command == "set_context":
            user.work_context = args.get("context", "")
            send_text(open_id, f"已记录工作上下文：{user.work_context}")
            return

    # Multi-task
    if command == "add_task":
            result = user.add_task(args.get("name", ""))
            send_text(open_id, result)
            return

    if command == "switch_task":
            result = user.switch_task(args.get("name", ""))
            send_text(open_id, result)
            return

    if command == "remove_task":
            result = user.remove_task(args.get("name", ""))
            send_text(open_id, result)
            return

    if command == "list_tasks":
            send_text(open_id, user.task_list_text())
            return

    # Org style learning
    if command == "learn_doc":
            content = args.get("content", "")
            if not content:
                send_text(open_id, "请在 `学习文档：` 后面输入文档内容或风格样本。")
                return
            add_org_doc(content)
            send_text(open_id, f"已学习文档内容（{len(content)}字）。新人模式的建议会参考此风格。")
            return

    # Achievements
    if command == "show_achievements":
            card = achievements_list_card(user.unlocked_achievements, ACHIEVEMENT_DEFS)
            send_card(open_id, card)
            return

    # Feishu workspace killer feature
    if command == "demo_workspace":
            send_text(open_id, "正在为你自动开通飞书工作台（多维表格 + 文档），约 5-10 秒...")
            try:
                ws = ensure_workspace(open_id, force=False)
                summary = workspace_summary_for_card(ws)
                send_card(open_id, workspace_welcome_card(
                    bitable_url=summary["bitable_url"],
                    onboarding_url=summary["onboarding_url"],
                    recovery_url=summary["recovery_url"],
                    complete=summary["complete"],
                ))
            except Exception as e:
                logger.exception("Workspace provisioning error: %s", e)
                send_text(open_id, f"工作台开通失败：{e}\n\n请联系管理员检查应用权限（bitable:app / docx:document）。")
            return

    if command == "list_decisions":
            decisions = list_recent_decisions(open_id, limit=8)
            if not decisions:
                send_text(open_id, "尚无决策记录。专注模式中收到群消息后会自动记录。")
                return
            lines = ["**最近 8 条决策（输入 `为什么 决策ID` 查看详情）：**\n"]
            for d in decisions:
                tag = "↩️" if d.rolled_back else " "
                lines.append(
                    f"{tag} `{d.decision_id}` [{d.classification_level} {d.classification_score:.2f}] "
                    f"{d.sender_name}: {d.message_preview[:30]}"
                )
            send_text(open_id, "\n".join(lines))
            return

    if command == "explain_decision":
            decision_id = args.get("id", "")
            decisions = list_recent_decisions(open_id, limit=200)
            target = next((d for d in decisions if d.decision_id == decision_id), None)
            if not target:
                send_text(open_id, f"未找到决策 `{decision_id}`。请先发 `最近决策` 查看可用 ID。")
                return
            send_text(open_id, explain_decision(target))
            return

    if command == "rollback_decision":
            decision_id = args.get("id", "")
            new_level = args.get("level", "")
            rec = rollback_decision(decision_id, new_level, "user_corrected_manually")
            if not rec:
                send_text(open_id, f"未找到决策 `{decision_id}`。")
                return
            send_text(
                open_id,
                f"已将决策 `{decision_id}` 从 {rec.classification_level} 回滚为 {new_level}。\n\n"
                f"你的反馈已写入发送者画像，下次类似消息会更准确。"
            )
            return

    if command == "show_workspace":
            ws = get_workspace(open_id)
            if not ws.is_complete():
                send_text(open_id, "你还没有工作台。发送 `演示工作台` 立即创建。")
                return
            summary = workspace_summary_for_card(ws)
            send_card(open_id, workspace_welcome_card(
                bitable_url=summary["bitable_url"],
                onboarding_url=summary["onboarding_url"],
                recovery_url=summary["recovery_url"],
                complete=True,
            ))
            return

    # ── v2 Agent-Pilot commands ──
    if command == "pilot_help":
            send_text(open_id, _pilot_help_text())
            return

    # Judge wow points (P4.5)
    if command == "pilot_context":
            try:
                from core.agent_pilot.harness import default_orchestrator
                orch = default_orchestrator()
                lines = ["🧠 **Context 快照**", ""]
                lines.append(f"工具：{len(orch.tools.names())} 个 — {', '.join(orch.tools.names()[:8])}…")
                lines.append(f"Skills：{', '.join(s.name for s in orch.skills.list())}")
                lines.append(f"权限模式：`{orch.permissions.mode.value}`")
                lines.append(f"最近 Hook：{len(orch.hooks.history())} 条")
                lines.append(f"最近事件：{len(orch.events())} 条")
                lines.append("\n详情：http://118.178.242.26/api/pilot/context")
                send_text(open_id, "\n".join(lines))
            except Exception as _e:
                send_text(open_id, f"context 查询失败：{_e}")
            return

    if command == "pilot_skills":
            try:
                from core.agent_pilot.harness import default_skills
                from bot.card_v2 import skills_list_card
                skills = [{"name": s.name, "description": s.description,
                           "source": s.source, "version": s.version,
                           "path": s.path}
                          for s in default_skills().list()]
                send_card(open_id, skills_list_card(skills))
            except Exception as _e:
                send_text(open_id, f"skills 查询失败：{_e}")
            return

    if command == "pilot_mcp":
            try:
                from core.agent_pilot.harness import default_mcp_manager
                mgr = default_mcp_manager()
                aliases = mgr.list_aliases() or ["(无)"]
                tools = mgr.list_tools()
                send_text(open_id,
                          "🔌 **MCP Servers**\n" +
                          "\n".join(f"- `{a}`" for a in aliases) +
                          f"\n\n总工具数：{len(tools)}")
            except Exception as _e:
                send_text(open_id, f"mcp 查询失败：{_e}")
            return

    if command == "pilot_plan_mode":
            intent = args.get("intent", "")
            if not intent:
                send_text(open_id, "发 `/plan <意图>` 进入 Plan Mode（只规划不执行）。")
                return
            try:
                from core.agent_pilot.service import launch as _pl
                plan = _pl(intent, user_open_id=open_id,
                           meta={"source": "feishu_p2p", "plan_mode": True,
                                 "permission_mode": "plan"},
                           async_run=False, execute=False)
                steps = "\n".join(f"  {i+1}. [{s.tool}] {s.description}"
                                  for i, s in enumerate(plan.steps[:12]))
                send_text(open_id,
                          "📝 **Plan Mode（只规划不执行）**\n"
                          f"Plan: `{plan.plan_id}`\n意图：{intent[:80]}\n\n"
                          f"共 {len(plan.steps)} 步：\n{steps}\n\n"
                          "确认执行请发 `/pilot " + intent[:40] + "`；调整请重新描述。")
            except Exception as _e:
                send_text(open_id, f"Plan Mode 失败：{_e}")
            return

    if command == "pilot_list":
            try:
                from core.agent_pilot.service import list_plans as _list_plans
                rows = _list_plans(user_open_id=open_id, limit=8)
            except Exception as e:
                send_text(open_id, f"获取 Pilot 列表失败：{e}")
                return
            if not rows:
                send_text(open_id, "尚无 Pilot 执行记录。\n\n发 `/pilot 把本周讨论做成评审 PPT` 触发一次试试。")
                return
            lines = ["🛫 **最近 Pilot 运行**\n"]
            import time as _t
            for r in rows:
                ts = _t.strftime("%m-%d %H:%M", _t.localtime(r.get("created_ts", 0)))
                lines.append(
                    f"- [{ts}] `{r['plan_id']}` {r['done_steps']}/{r['total_steps']} 完成 · {r['intent']}"
                )
            lines.append("\n详情请访问 Dashboard：http://118.178.242.26/dashboard/pilot")
            send_text(open_id, "\n".join(lines))
            return

    if command == "pilot_run":
            intent = args.get("intent", "")
            if not intent:
                send_text(open_id, _pilot_help_text())
                return
            try:
                from core.agent_pilot.service import launch as _pilot_launch
                plan = _pilot_launch(intent, user_open_id=open_id,
                                     meta={"source": "feishu_p2p"}, async_run=True)
            except Exception as e:
                logger.exception("pilot_run error: %s", e)
                send_text(open_id, f"Agent-Pilot 启动失败：{e}")
                return
            _wm_append(open_id, "pilot_launched", {"plan_id": plan.plan_id, "intent": intent[:80]})
            step_preview = "\n".join(
                f"  {i+1}. [{s.tool}] {s.description}" for i, s in enumerate(plan.steps[:6])
            )
            send_text(
                open_id,
                "🛫 **Agent-Pilot 已启动**\n"
                f"Plan: `{plan.plan_id}`\n"
                f"意图：{intent[:80]}\n\n"
                f"📋 计划（共 {len(plan.steps)} 步）：\n{step_preview}\n\n"
                f"实时进度：http://118.178.242.26/dashboard/pilot?plan_id={plan.plan_id}\n"
                f"Flutter/Web 客户端会自动刷新。完成后我会再发一条汇总。"
            )
            # Schedule completion summary (fire-and-forget in case scheduler missing)
            try:
                import threading as _th
                def _notify_when_done():
                    import time as _t2
                    from core.agent_pilot.service import get_plan as _gp
                    start = _t2.time()
                    while _t2.time() - start < 180:
                        _t2.sleep(3)
                        p2 = _gp(plan.plan_id)
                        if not p2:
                            continue
                        pending = [s for s in p2.steps if s.status in ("pending", "running")]
                        if not pending:
                            done = [s for s in p2.steps if s.status == "done"]
                            failed = [s for s in p2.steps if s.status == "failed"]
                            urls = []
                            for s in p2.steps:
                                for key in ("url", "pptx_url", "pdf_url", "share_url"):
                                    u = (s.result or {}).get(key)
                                    if u:
                                        urls.append(f"{s.tool}: {u}")
                                        break
                            summary = [
                                "🛬 **Agent-Pilot 完成**",
                                f"`{plan.plan_id}` · {len(done)}/{len(p2.steps)} 完成"
                                + (f"，{len(failed)} 失败" if failed else ""),
                                "",
                                "📦 产物：",
                            ]
                            summary += urls[:8] or ["（本次运行产物已保存到服务器 data/pilot_artifacts/）"]
                            summary.append(f"\n汇总链接：http://118.178.242.26/pilot/{plan.plan_id}")
                            try:
                                send_text(open_id, "\n".join(summary))
                            except Exception:
                                pass
                            return
                _th.Thread(target=_notify_when_done, daemon=True).start()
            except Exception:
                pass
            return

    # ── v3 commands: weekly report / monthly wrapped / memory / data ──

    if command == "weekly_report":
            send_text(open_id, "正在基于你的工作记忆生成本周周报，请稍候...")
            try:
                from core.work_review.weekly_report import generate_weekly_report as gen_weekly
                report = gen_weekly(open_id, publish=True)
                header = (
                    f"📋 **本周周报**（{report.stats.get('focus_count', 0)} 次专注 · "
                    f"{report.stats.get('focus_minutes', 0)} 分钟）\n\n"
                )
                send_text(open_id, header + report.body_md)
            except Exception as e:
                logger.exception("weekly_report error: %s", e)
                send_text(open_id, f"周报生成失败：{e}")
            return

    if command == "monthly_wrapped":
            send_text(open_id, "正在生成月度 Wrapped 卡片...")
            try:
                from core.work_review.monthly_wrapped import generate_monthly_wrapped
                card_data = generate_monthly_wrapped(open_id, days=30)
                lines = [f"🎵 **{card_data.headline}**\n"]
                for b in card_data.bullets:
                    lines.append(f"• {b}")
                lines.append(f"\n📊 统计：")
                for k, v in card_data.stats.items():
                    lines.append(f"  - {k}: {v}")
                send_text(open_id, "\n".join(lines))
            except Exception as e:
                logger.exception("monthly_wrapped error: %s", e)
                send_text(open_id, f"月报生成失败：{e}")
            return

    if command == "show_memory":
            try:
                from core.flow_memory.archival import query_archival
                from core.flow_memory.working import WorkingMemory
                wm = WorkingMemory.load(open_id)
                recent_events = wm.recent(n=10)
                archived = query_archival(open_id, limit=5)

                lines = ["🧠 **我的记忆**\n"]
                lines.append(f"**工作记忆**（最近 {len(wm.events)}/{wm.capacity} 条事件）：")
                if recent_events:
                    for ev in recent_events[-5:]:
                        import time as _time
                        ts_str = _time.strftime("%m-%d %H:%M", _time.localtime(ev.ts))
                        payload_preview = str(ev.payload)[:60] if ev.payload else ""
                        lines.append(f"  [{ts_str}] {ev.kind}: {payload_preview}")
                else:
                    lines.append("  （暂无事件）")

                lines.append(f"\n**长期归档**（最近 {len(archived)} 条摘要）：")
                if archived:
                    for a in archived:
                        import time as _time
                        ts_str = _time.strftime("%m-%d %H:%M", _time.localtime(a.ts))
                        lines.append(f"  [{ts_str}] ({a.kind}) {a.summary_md[:80]}")
                else:
                    lines.append("  （暂无归档摘要）")

                send_text(open_id, "\n".join(lines))
            except Exception as e:
                logger.exception("show_memory error: %s", e)
                send_text(open_id, f"记忆查询失败：{e}")
            return

    if command == "delete_my_data":
            send_text(open_id, "⚠️ 确认删除你的所有数据？包括工作记忆、归档摘要、发送方画像。\n\n请在 30 秒内回复 `确认删除` 执行操作。")
            return

    if command == "rollback_recent":
            decisions = list_recent_decisions(open_id, limit=1)
            if not decisions:
                send_text(open_id, "暂无可撤回的决策。")
                return
            d = decisions[0]
            rec = rollback_decision(d.decision_id, "P0", "user_quick_rollback")
            if rec:
                send_text(open_id, f"已撤回最近一条决策 `{d.decision_id}`（{d.classification_level} → P0）。")
            else:
                send_text(open_id, "撤回失败，请用 `最近决策` 查看后手动回滚。")
            return

    # ── Rookie / Mentor (LarkMentor v1) ──
    if command == "start_rookie":
            user.rookie_mode = True
            send_text(
                open_id,
                "✨ **LarkMentor 新人模式已开启**\n\n"
                "表达层带教 4 个 Skill：\n"
                "📝 `帮我看看：消息内容` · MentorWrite（消息起草：NVC + 3 版改写 + 风险）\n"
                "📋 `任务确认：任务描述` · MentorTask（任务澄清：模糊度打分 + 澄清问题）\n"
                "🤝 `重新入职` · MentorOnboard（新人入职：5 问知识沉淀）\n"
                "📊 `写周报：本周内容` · MentorReview（周报回顾：STAR 引用周报）\n\n"
                "🤖 `@Mentor xxx` · 自动路由（写作/任务/复盘/入职）\n"
                "📚 `导入文档：xxx` · 入库到组织 RAG（自动 PII 扫描）\n"
                "🔍 `查询知识：xxx` · 验证 RAG 召回\n"
                "🛎 `开启主动建议` / `关闭主动建议`\n"
                "📓 `我的成长档案` · 拿 Docx 链接 · `我的入职信息` 看 onboarding"
            )
            # 自动创建成长档案
            try:
                token = v4_growth.ensure_growth_doc(open_id)
                if token:
                    send_text(open_id, f"📓 已为你创建《我的新手成长记录》Docx，发送 `我的成长档案` 拿链接。")
            except Exception:
                pass
            # 触发 onboarding 流（如果还没做过）
            try:
                if not mentor_onboard.is_in_progress(open_id):
                    sess = mentor_onboard.start(open_id)
                    if not sess.completed:
                        q = sess.next_question
                        if q is not None:
                            send_text(
                                open_id,
                                f"🤝 **MentorOnboard 团队融入流（{sess.progress}）**\n\n"
                                f"[{q['dim']}] {q['label']}\n\n"
                                f"（直接回复你的答案即可；不想做发 `跳过入职` 退出）"
                            )
            except Exception as e:
                logger.debug("onboard_start_skipped err=%s", e)
            return

    if command == "stop_rookie":
            user.rookie_mode = False
            send_text(open_id, "新人模式已关闭。Mentor 主动建议也已暂停。")
            return

    if command == "rookie_review":
            msg = args.get("message", "")
            if not msg:
                send_text(open_id, "请在 `帮我看看：` 后面输入你要审核的消息内容。")
                return
            review = v4_write.review(open_id, msg)
            send_card(open_id, mentor_review_card(review.to_dict()))
            try:
                v4_growth.append_entry(
                    open_id, kind="writing", original=msg,
                    improved=review.three_versions.get("neutral", msg),
                    citations=review.citations,
                )
            except Exception as e:
                logger.debug("growth_append_skipped err=%s", e)
            return

    if command == "rookie_task":
            task = args.get("task", "")
            if not task:
                send_text(open_id, "请在 `任务确认：` 后面输入任务描述。")
                return
            clarif = v4_task.clarify(open_id, task)
            send_card(open_id, mentor_clarify_card(clarif.to_dict()))
            try:
                improved = (
                    "; ".join(clarif.suggested_questions)
                    if clarif.needs_clarification
                    else f"{clarif.task_understanding} | {clarif.delivery_plan}"
                )
                v4_growth.append_entry(
                    open_id, kind="task", original=task,
                    improved=improved, citations=clarif.citations,
                )
            except Exception:
                pass
            return

    if command == "rookie_weekly":
            content = args.get("content", "")
            # v4: weekly is now driven by FlowMemory, but accept hint text too.
            wk = v4_weekly.draft(open_id, user_meta=content[:120] if content else "")
            send_card(open_id, mentor_weekly_card(wk.to_dict()))
            return

    # ── v4 Mentor: knowledge base ──
    if command == "kb_import":
            content = args.get("content", "")
            if not content:
                send_text(open_id, "请在 `导入文档：` 后面贴入文档内容。")
                return
            res = v4_kb.import_text(open_id, source=f"manual_{int(_time.time())}.md", text=content)
            if res.ok:
                send_text(
                    open_id,
                    f"✅ 已导入 {res.chunks_added} 段。Mentor 后续回答会自动引用此文档。",
                )
            else:
                if res.rejected_reason == "pii_detected":
                    send_text(
                        open_id,
                        f"⚠️ 检测到敏感信息（{', '.join(res.pii_kinds)}），未入库。"
                        "请手动去敏后再试。",
                    )
                else:
                    send_text(open_id, f"导入失败：{res.rejected_reason}")
            return

    if command == "kb_import_wiki":
            url = args.get("url", "")
            send_text(
                open_id,
                f"📚 正在尝试拉取 wiki：{url}\n\n"
                "⚠️ 飞书 Wiki API 权限需企业管理员审批，目前 v4 提供降级路径："
                "请用 `导入文档：内容` 手动粘贴文档内容。"
            )
            return

    if command == "kb_search":
            q = args.get("query", "")
            hits = v4_kb.search(open_id, q)
            if not hits:
                send_text(open_id, f"知识库无命中：{q}\n（可能尚未导入相关文档）")
                return
            lines = [f"**Top {len(hits)} 命中**（method={hits[0].method}）:\n"]
            for i, h in enumerate(hits, 1):
                lines.append(f"{i}. {h.citation_tag()} score={h.score:.3f}")
                lines.append(f"   {h.chunk.text[:120]}")
            send_text(open_id, "\n".join(lines))
            return

    # LarkMentor v1: KB document list & per-source delete (GDPR)
    if command == "kb_list":
            sources = v4_kb.list_sources(open_id)
            if not sources:
                send_text(open_id, "知识库为空。发送 `导入文档：xxx` 入库。")
                return
            lines = [f"📚 **你的知识库**（{len(sources)} 个文档）\n"]
            for s in sources:
                ts_str = _time.strftime("%m-%d %H:%M", _time.localtime(s["last_ts"]))
                lines.append(f"- `{s['source']}` · {s['chunks']} 段 · {ts_str}")
            lines.append("\n删除单个文档：`删除知识：<source>`；全部清空：`删除我的数据`")
            send_text(open_id, "\n".join(lines))
            return

    if command == "kb_delete_source":
            src = args.get("source", "")
            if not src:
                send_text(open_id, "请在 `删除知识：` 后面跟文档名。先发 `知识库列表` 看可选项。")
                return
            n = v4_kb.delete_source(open_id, src)
            if n > 0:
                send_text(open_id, f"✅ 已删除 `{src}` 共 {n} 段。其它文档保留。")
            else:
                send_text(open_id, f"未找到 `{src}`。先发 `知识库列表` 确认源名。")
            return

    # ── v4 Mentor: explicit role routing ──
    if command == "mentor_route":
            text_in = args.get("input", "")
            if not text_in:
                send_text(open_id, "请在 `@Mentor` 后面输入你的问题。")
                return
            decision = v4_router.route(text_in)
            if decision.role == "writing":
                review = v4_write.review(open_id, text_in)
                send_card(open_id, mentor_review_card(review.to_dict()))
            elif decision.role == "task":
                clarif = v4_task.clarify(open_id, text_in)
                send_card(open_id, mentor_clarify_card(clarif.to_dict()))
            elif decision.role == "weekly":
                wk = v4_weekly.draft(open_id)
                send_card(open_id, mentor_weekly_card(wk.to_dict()))
            else:
                send_text(
                    open_id,
                    f"Mentor 路由：{decision.role}（{decision.method}/{decision.confidence:.2f}）\n"
                    f"理由：{decision.why}\n\n"
                    "如需具体能力，请直接发：`帮我看看:` / `任务确认:` / `写周报:`"
                )
            return

    # ── v4 Mentor: proactive toggle ──
    if command == "proactive_on":
            v4_proactive.set_enabled(user, True)
            send_text(open_id, "✅ 已开启 Mentor 主动建议。收到 P0/P1 时会私聊 3 版回复（5min 频控 / 24h 上限 3 次）。")
            return

    if command == "proactive_off":
            v4_proactive.set_enabled(user, False)
            send_text(open_id, "🔕 已关闭 Mentor 主动建议。你仍可主动用 `帮我看看：` 或 `@Mentor` 调用。")
            return

    # ── v4 Mentor: growth journal ──
    if command == "show_growth":
            from core.mentor.growth_doc import load_entries

            week = load_entries(open_id, since_ts=int(_time.time()) - 7 * 86400)
            total = load_entries(open_id)
            doc_url = ""
            if user.growth_doc_token:
                doc_url = f"https://feishu.cn/docx/{user.growth_doc_token}"
            send_card(open_id, mentor_growth_card(
                week_count=len(week), total_count=len(total), doc_url=doc_url,
            ))
            return

    # ── LarkMentor v1: onboarding ──
    if command == "onboard_reset":
            mentor_onboard.reset(open_id)
            send_text(open_id, "已清空 onboarding。发送 `开启新人模式` 重新走 5 问入职流。")
            return

    if command == "onboard_show":
            sess = mentor_onboard.get_session(open_id)
            if sess is None or not sess.answers:
                send_text(open_id, "暂无 onboarding 记录。发送 `开启新人模式` 触发 5 问入职流。")
                return
            send_text(open_id, mentor_onboard.render_summary(sess))
            return

    if command == "show_growth_week":
            from core.mentor.growth_doc import load_entries

            week = load_entries(open_id, since_ts=int(_time.time()) - 7 * 86400)
            if not week:
                send_text(open_id, "本周暂无 Mentor 出手记录。")
                return
            lines = [f"📓 **本周 {len(week)} 条 Mentor 记录**\n"]
            for e in week[-10:]:
                ts_str = _time.strftime("%m-%d %H:%M", _time.localtime(e.ts))
                lines.append(f"- [{ts_str}] [{e.kind}] {e.original[:40]} → {e.improved[:40]}")
            send_text(open_id, "\n".join(lines))
            return

    # ── LarkMentor v1: 如果用户在 onboarding 中，把消息当答案 ──
    if mentor_onboard.is_in_progress(open_id):
            if text.strip() in ("跳过入职", "skip onboarding"):
                mentor_onboard.reset(open_id)
                send_text(open_id, "已跳过 onboarding。可随时发 `开启新人模式` 重新触发。")
                return
            sess, just_done = mentor_onboard.submit_answer(open_id, text)
            if just_done:
                send_text(
                    open_id,
                    "🎉 **MentorOnboard 完成**\n\n"
                    + mentor_onboard.render_summary(sess)
                    + "\n\n这些信息已自动入库，后续 Mentor 出手会优先参考。"
                )
            else:
                q = sess.next_question
                if q is not None:
                    send_text(
                        open_id,
                        f"✓ 已记录\n\n🤝 **MentorOnboard（{sess.progress}）**\n"
                        f"[{q['dim']}] {q['label']}",
                    )
            return

    # Unknown DM
    if user.rookie_mode:
            send_text(open_id, f"收到消息。发送 `帮助` 查看所有指令。\n\n新人模式已开启，试试 `帮我看看：{text[:20]}` 来审核你的消息。")
            return

    # Not focusing and unknown command → show welcome card
    if not user.is_focusing():
            send_card(open_id, first_time_welcome_card())
            return

    # User sent a p2p message to Bot while focusing → treat as group-style input
    chat_name = f"私聊:{sender_open_id[-6:]}"
    result = _active_process_message(
            user=user,
            sender_name=sender_name,
            sender_id=sender_open_id,
            message_id=message_id,
            content=text,
            chat_name=chat_name,
    )
    _wm_append(open_id, "message", {
        "sender_name": sender_name, "level": result.get("level", "P3"),
        "action": result.get("action", "archive"), "content": text[:60],
    })
    _wm_append(open_id, "decision", {
        "level": result.get("level", "P3"), "action": result.get("action", "archive"),
        "score": result.get("score", 0), "used_llm": result.get("used_llm", False),
    })
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
                f"LarkMentor 已自动结束保护模式，请尽快查看。"
            )
            _cancel_focus_expiry(open_id)
            stats = user.end_focus()
            recovery_text_p2p = generate_recovery(user, stats)
            send_card(open_id, recovery_card(stats, recovery_text_p2p))


def on_message_receive(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    t = threading.Thread(target=_handle_in_thread, args=(data,), daemon=True)
    t.start()
