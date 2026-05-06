"""Agent Pilot task flow – /pilot commands, plan mode, context, skills, MCP."""

import logging
import time as _time

from bot.handlers._common import wm_append
from bot.message_sender import reply_text, send_card, send_text
from config import Config

logger = logging.getLogger("agent_pilot.handler.pilot")


def _dashboard_url(path: str = "") -> str:
    """Build a fully-qualified dashboard URL.

    Strips any port suffix that's not actually exposed publicly (e.g. :8001 was
    blocked by firewall in v12). Falls back to localhost only as last resort.
    """
    base = (Config.DASHBOARD_PUBLIC_URL or "").rstrip("/")
    if not base:
        base = f"http://localhost:{Config.DASHBOARD_PORT}"
    if not path.startswith("/") and path:
        path = "/" + path
    return f"{base}{path}"

# All pilot-related command names
PILOT_COMMANDS = frozenset(
    {
        "pilot_help",
        "pilot_run",
        "pilot_list",
        "pilot_plan_mode",
        "pilot_context",
        "pilot_skills",
        "pilot_mcp",
    }
)


def pilot_help_text() -> str:
    return (
        "🚀 **Agent-Pilot 使用指南**\n\n"
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
        f"  {_dashboard_url('/dashboard/pilot')}\n\n"
        "**详细文档**：\n"
        "  https://github.com/bcefghj/agent-pilot\n\n"
        "💡 提示：需求描述越具体，生成效果越好！"
    )


def handle_pilot_command(command: str, args: dict, open_id: str, user, text: str) -> bool:
    """Handle a pilot-related command. Returns True if handled."""
    if command not in PILOT_COMMANDS:
        return False

    handler = _DISPATCH.get(command)
    if handler:
        handler(args, open_id, user, text)
        return True
    return False


def handle_group_pilot(sender_open_id: str, message_id: str, intent: str, chat_name: str):
    """Handle /pilot command from a group chat (does NOT require focus mode)."""
    try:
        from core.agent_pilot.service import launch as _pilot_launch

        plan = _pilot_launch(
            intent,
            user_open_id=sender_open_id,
            meta={"source": "feishu_group", "chat_id": "", "chat_name": chat_name},
            async_run=True,
        )
        reply_text(
            message_id,
            f"🛫 Agent-Pilot 已启动 `{plan.plan_id}`（共 {len(plan.steps)} 步）。"
            f"完成后将在此群回帖汇总。\n实时进度：{_dashboard_url()}/dashboard/pilot?plan_id={plan.plan_id}",
        )
    except Exception as e:
        logger.exception("group pilot_run error: %s", e)
        reply_text(message_id, f"Agent-Pilot 启动失败：{e}")


# ── Individual command handlers ──


def _cmd_pilot_help(args, open_id, user, text):
    send_text(open_id, pilot_help_text())


def _cmd_pilot_run(args, open_id, user, text):
    intent = args.get("intent", "")
    if not intent:
        send_text(open_id, pilot_help_text())
        return
    try:
        from core.agent_pilot.service import launch as _pilot_launch

        plan = _pilot_launch(intent, user_open_id=open_id, meta={"source": "feishu_p2p"}, async_run=True)
    except Exception as e:
        logger.exception("pilot_run error: %s", e)
        send_text(open_id, f"Agent-Pilot 启动失败：{e}")
        return
    wm_append(open_id, "pilot_launched", {"plan_id": plan.plan_id, "intent": intent[:80]})
    step_preview = "\n".join(f"  {i + 1}. [{s.tool}] {s.description}" for i, s in enumerate(plan.steps[:6]))
    send_text(
        open_id,
        "🛫 **Agent-Pilot 已启动**\n"
        f"Plan: `{plan.plan_id}`\n"
        f"意图：{intent[:80]}\n\n"
        f"📋 计划（共 {len(plan.steps)} 步）：\n{step_preview}\n\n"
        f"实时进度：{_dashboard_url()}/dashboard/pilot?plan_id={plan.plan_id}\n"
        f"Flutter/Web 客户端会自动刷新。完成后我会再发一条汇总。",
    )
    _schedule_completion_notify(open_id, plan)


def _cmd_pilot_list(args, open_id, user, text):
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
        lines.append(f"- [{ts}] `{r['plan_id']}` {r['done_steps']}/{r['total_steps']} 完成 · {r['intent']}")
    lines.append(f"\n详情请访问 Dashboard：{_dashboard_url('/dashboard/pilot')}")
    send_text(open_id, "\n".join(lines))


def _cmd_pilot_plan_mode(args, open_id, user, text):
    intent = args.get("intent", "")
    if not intent:
        send_text(open_id, "发 `/plan <意图>` 进入 Plan Mode（只规划不执行）。")
        return
    try:
        from core.agent_pilot.service import launch as _pl

        plan = _pl(
            intent,
            user_open_id=open_id,
            meta={"source": "feishu_p2p", "plan_mode": True, "permission_mode": "plan"},
            async_run=False,
            execute=False,
        )
        steps = "\n".join(f"  {i + 1}. [{s.tool}] {s.description}" for i, s in enumerate(plan.steps[:12]))
        send_text(
            open_id,
            "📝 **Plan Mode（只规划不执行）**\n"
            f"Plan: `{plan.plan_id}`\n意图：{intent[:80]}\n\n"
            f"共 {len(plan.steps)} 步：\n{steps}\n\n"
            "确认执行请发 `/pilot " + intent[:40] + "`；调整请重新描述。",
        )
    except Exception as _e:
        send_text(open_id, f"Plan Mode 失败：{_e}")


def _cmd_pilot_context(args, open_id, user, text):
    try:
        from core.agent_pilot.harness import default_orchestrator

        orch = default_orchestrator()
        lines = ["🧠 **Context 快照**", ""]
        lines.append(f"工具：{len(orch.tools.names())} 个 — {', '.join(orch.tools.names()[:8])}…")
        lines.append(f"Skills：{', '.join(s.name for s in orch.skills.list())}")
        lines.append(f"权限模式：`{orch.permissions.mode.value}`")
        lines.append(f"最近 Hook：{len(orch.hooks.history())} 条")
        lines.append(f"最近事件：{len(orch.events())} 条")
        lines.append(f"\n详情：{_dashboard_url('/api/pilot/context')}")
        send_text(open_id, "\n".join(lines))
    except Exception as _e:
        send_text(open_id, f"context 查询失败：{_e}")


def _cmd_pilot_skills(args, open_id, user, text):
    try:
        from bot.card_v2 import skills_list_card
        from core.agent_pilot.harness import default_skills

        skills = [
            {"name": s.name, "description": s.description, "source": s.source, "version": s.version, "path": s.path}
            for s in default_skills().list()
        ]
        send_card(open_id, skills_list_card(skills))
    except Exception as _e:
        send_text(open_id, f"skills 查询失败：{_e}")


def _cmd_pilot_mcp(args, open_id, user, text):
    try:
        from core.agent_pilot.harness import default_mcp_manager

        mgr = default_mcp_manager()
        aliases = mgr.list_aliases() or ["(无)"]
        tools = mgr.list_tools()
        send_text(
            open_id, "🔌 **MCP Servers**\n" + "\n".join(f"- `{a}`" for a in aliases) + f"\n\n总工具数：{len(tools)}"
        )
    except Exception as _e:
        send_text(open_id, f"mcp 查询失败：{_e}")


# ── Helpers ──


def _schedule_completion_notify(open_id: str, plan):
    """Fire-and-forget thread that polls for plan completion and sends summary."""
    try:
        import threading as _th

        def _notify_when_done():
            import time as _t2
            from core.agent_pilot.service import get_plan as _gp

            start = _t2.time()
            while _t2.time() - start < 300:
                _t2.sleep(3)
                p2 = _gp(plan.plan_id)
                if not p2:
                    continue
                pending = [s for s in p2.steps if s.status in ("pending", "running")]
                if not pending:
                    done = [s for s in p2.steps if s.status == "done"]
                    failed = [s for s in p2.steps if s.status == "failed"]
                    urls = []
                    seen_urls = set()
                    content_preview = ""
                    for s in p2.steps:
                        result = s.result or {}
                        if not content_preview and result.get("markdown_content"):
                            raw = result["markdown_content"]
                            content_preview = raw[:300].replace("\n", " ").strip()
                            if len(raw) > 300:
                                content_preview += "..."

                        for key in ("feishu_url", "url", "pptx_url", "pdf_url", "share_url"):
                            u = result.get(key)
                            if not u or u in seen_urls:
                                continue
                            if u.startswith("/artifacts/") or u.startswith("file://"):
                                continue
                            if "localhost" in u:
                                continue
                            seen_urls.add(u)
                            label_map = {
                                "feishu_url": "📄 飞书文档",
                                "pptx_url": "📊 演示稿PPT",
                                "pdf_url": "📑 PDF",
                                "share_url": "🔗 分享链接",
                                "url": result.get("title") or s.tool,
                            }
                            label = label_map.get(key, s.tool)
                            urls.append(f"  • {label}：{u}")
                            break

                    summary = [
                        "🛬 **Agent-Pilot 任务完成**",
                        f"`{plan.plan_id}` · {len(done)}/{len(p2.steps)} 步完成"
                        + (f"，{len(failed)} 步失败" if failed else ""),
                    ]
                    if content_preview:
                        summary += ["", "📝 内容摘要：", content_preview]
                    summary += ["", "📦 产物链接："]
                    summary += urls[:8] or ["  （产物已保存到飞书云文档）"]
                    summary.append(f"\n📊 进度面板：{_dashboard_url(f'/dashboard/pilot?plan_id={plan.plan_id}')}")
                    try:
                        send_text(open_id, "\n".join(summary))
                    except Exception as e:
                        logger.debug("pilot notify send_text failed: %s", e)
                    return

        _th.Thread(target=_notify_when_done, daemon=True).start()
    except Exception as e:
        logger.warning("pilot async run launch failed: %s", e)


# Command dispatch table
_DISPATCH = {
    "pilot_help": _cmd_pilot_help,
    "pilot_run": _cmd_pilot_run,
    "pilot_list": _cmd_pilot_list,
    "pilot_plan_mode": _cmd_pilot_plan_mode,
    "pilot_context": _cmd_pilot_context,
    "pilot_skills": _cmd_pilot_skills,
    "pilot_mcp": _cmd_pilot_mcp,
}
