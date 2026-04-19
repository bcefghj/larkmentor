"""Module 2: Flow Detector – work state recognition and focus mode management."""

import re
import logging

from memory.user_state import UserState, get_user
from config import Config

logger = logging.getLogger("flowguard.detector")


def parse_command(text: str) -> dict:
    """Parse user command text into structured action."""
    text = text.strip()

    # Focus commands（含 LarkMentor 菜单用语：进入勿扰 / 退出勿扰 等）
    if text in (
        "开始专注",
        "开启专注",
        "focus",
        "专注",
        "开始保护",
        "进入专注",
        "进入勿扰",
        "开启勿扰",
        "勿扰开",
        "专注开",
    ):
        return {"command": "start_focus", "args": {"duration": 0}}

    match = re.match(r"(?:进入|开启)?勿扰\s*(\d+)\s*(?:分钟|min)?$", text)
    if match:
        return {"command": "start_focus", "args": {"duration": int(match.group(1))}}

    match = re.match(r"(?:开始|开启|进入)?专注\s*(\d+)\s*(?:分钟|min)?$", text)
    if match:
        return {"command": "start_focus", "args": {"duration": int(match.group(1))}}

    match = re.match(r"focus\s+(\d+)", text, re.I)
    if match:
        return {"command": "start_focus", "args": {"duration": int(match.group(1))}}

    if text in (
        "结束专注",
        "done",
        "结束保护",
        "停止专注",
        "关闭专注",
        "退出专注",
        "退出勿扰",
        "结束勿扰",
        "勿扰关",
        "退出勿扰 · 汇总",
        "专注关",
    ):
        return {"command": "end_focus", "args": {}}

    # Whitelist
    match = re.match(r"白名单\s+(.+)", text)
    if match:
        return {"command": "set_whitelist", "args": {"name": match.group(1).strip()}}

    match = re.match(r"移除白名单\s+(.+)", text)
    if match:
        return {"command": "remove_whitelist", "args": {"name": match.group(1).strip()}}

    if text in ("白名单列表", "白名单"):
        return {"command": "list_whitelist", "args": {}}

    # Status & report
    if text in ("状态", "status", "今天的状态", "当前状态"):
        return {"command": "show_status", "args": {}}

    if text in ("今日报告", "日报", "report", "今日简报", "今日守护简报"):
        return {"command": "daily_report", "args": {}}

    # v3: weekly report (FlowMemory-based)
    if text in (
        "本周周报",
        "周报",
        "生成周报",
        "weekly",
        "weekly report",
        "周度简报",
    ):
        return {"command": "weekly_report", "args": {}}

    # v3: monthly wrapped
    if text in ("月报", "月度报告", "wrapped", "monthly"):
        return {"command": "monthly_wrapped", "args": {}}

    # v3: memory recall
    if text in (
        "我的记忆",
        "记忆",
        "memory",
        "我的数据",
        "组织记忆",
        "组织上下文",
    ):
        return {"command": "show_memory", "args": {}}

    # v3: delete my data
    if text in ("删除我的数据", "清除我的数据", "delete my data"):
        return {"command": "delete_my_data", "args": {}}

    # v3: rollback recent decision (shortcut)
    if text in ("撤回最近决策", "撤回"):
        return {"command": "rollback_recent", "args": {}}

    if text in ("帮助", "help", "指令", "命令"):
        return {"command": "help", "args": {}}

    # Multi-task commands
    match = re.match(r"添加任务[：:](.+)", text, re.S)
    if match:
        return {"command": "add_task", "args": {"name": match.group(1).strip()}}

    match = re.match(r"切换任务[：:](.+)", text, re.S)
    if match:
        return {"command": "switch_task", "args": {"name": match.group(1).strip()}}

    match = re.match(r"删除任务[：:](.+)", text, re.S)
    if match:
        return {"command": "remove_task", "args": {"name": match.group(1).strip()}}

    if text in ("任务列表", "我的任务", "tasks"):
        return {"command": "list_tasks", "args": {}}

    # Org style learning (v3)
    match = re.match(r"学习文档[：:](.+)", text, re.S)
    if match:
        return {"command": "learn_doc", "args": {"content": match.group(1).strip()}}

    # v4 Mentor: knowledge base import / search
    match = re.match(r"导入文档[：:](.+)", text, re.S)
    if match:
        return {"command": "kb_import", "args": {"content": match.group(1).strip()}}

    match = re.match(r"导入wiki[：:]\s*(\S+)", text, re.I)
    if match:
        return {"command": "kb_import_wiki", "args": {"url": match.group(1).strip()}}

    match = re.match(r"查询知识[：:](.+)", text, re.S)
    if match:
        return {"command": "kb_search", "args": {"query": match.group(1).strip()}}

    # LarkMentor v1: KB document management
    if text in ("知识库列表", "我的知识库", "kb list"):
        return {"command": "kb_list", "args": {}}

    match = re.match(r"删除知识[：:]\s*(.+)", text, re.S)
    if match:
        return {"command": "kb_delete_source", "args": {"source": match.group(1).strip()}}

    # v4 Mentor: explicit role @Mentor / @教练（兼容）
    match = re.match(r"@?(?:Mentor|mentor|教练)\s+(.+)", text, re.S)
    if match:
        return {"command": "mentor_route", "args": {"input": match.group(1).strip()}}

    # v4 Mentor: proactive toggle
    if text in ("开启主动建议", "开启主动", "enable proactive"):
        return {"command": "proactive_on", "args": {}}
    if text in ("关闭主动建议", "关闭主动", "disable proactive"):
        return {"command": "proactive_off", "args": {}}

    # v4 Mentor: growth journal
    if text in ("我的成长档案", "成长档案", "我的成长", "growth"):
        return {"command": "show_growth", "args": {}}
    if text in ("查看本周成长", "本周成长"):
        return {"command": "show_growth_week", "args": {}}

    # ── LarkMentor v1: onboarding flow (团队融入) ──
    if text in ("重新入职", "重新onboarding", "重新 onboarding", "reset onboarding"):
        return {"command": "onboard_reset", "args": {}}
    if text in ("我的入职信息", "查看入职", "onboarding"):
        return {"command": "onboard_show", "args": {}}

    # Rookie Buddy
    if text in ("开启新人模式", "新人模式"):
        return {"command": "start_rookie", "args": {}}

    if text in ("关闭新人模式",):
        return {"command": "stop_rookie", "args": {}}

    match = re.match(r"帮我看看[：:](.+)", text, re.S)
    if match:
        return {"command": "rookie_review", "args": {"message": match.group(1).strip()}}

    match = re.match(r"任务确认[：:](.+)", text, re.S)
    if match:
        return {"command": "rookie_task", "args": {"task": match.group(1).strip()}}

    match = re.match(r"写周报[：:](.+)", text, re.S)
    if match:
        return {"command": "rookie_weekly", "args": {"content": match.group(1).strip()}}

    # Work context
    match = re.match(r"我在做[：:](.+)", text, re.S)
    if match:
        return {"command": "set_context", "args": {"context": match.group(1).strip()}}

    # Achievements
    if text in ("成就", "我的成就", "achievements"):
        return {"command": "show_achievements", "args": {}}

    # Workspace killer feature
    if text in ("演示工作台", "创建工作台", "demo workspace", "workspace"):
        return {"command": "demo_workspace", "args": {}}

    if text in ("我的工作台", "工作台", "我的看板"):
        return {"command": "show_workspace", "args": {}}

    # Decision explain & rollback (advanced features)
    if text in ("最近决策", "决策记录", "audit"):
        return {"command": "list_decisions", "args": {}}

    match = re.match(r"为什么\s*(.+)", text)
    if match:
        return {"command": "explain_decision", "args": {"id": match.group(1).strip()}}

    match = re.match(r"回滚\s*([\w_]+)\s+(P[0-3])", text)
    if match:
        return {"command": "rollback_decision",
                "args": {"id": match.group(1), "level": match.group(2)}}

    return {"command": "unknown", "args": {"text": text}}


def get_status_text(user: UserState) -> str:
    if user.is_focusing():
        from utils.time_utils import now_ts, fmt_duration
        elapsed = now_ts() - user.focus_start_ts
        pending_count = len(user.pending_messages)
        task_info = f"\n当前任务：{user.active_task_name}" if user.active_task_name else ""
        return (
            f"🛡️ **当前状态：深度专注中**\n"
            f"已专注：{fmt_duration(elapsed)}\n"
            f"期间消息：{pending_count} 条{task_info}\n"
            f"白名单：{', '.join(user.whitelist) if user.whitelist else '无'}\n"
            f"新人模式：{'开启' if user.rookie_mode else '关闭'}"
        )
    else:
        task_info = f"\n当前任务：{user.active_task_name}" if user.active_task_name else ""
        return (
            f"💤 **当前状态：普通模式**\n"
            f"今日被打断：{user.daily_interrupt_count} 次{task_info}\n"
            f"白名单：{', '.join(user.whitelist) if user.whitelist else '无'}\n"
            f"新人模式：{'开启' if user.rookie_mode else '关闭'}\n\n"
            f"发送 `开始专注` 进入保护模式"
        )
