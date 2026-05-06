"""IM 任务卡片 – PRD §5.2 落地.

The task card has six visual zones: 识别摘要 / 任务计划 / 上下文状态 /
执行人 / 行动按钮 / 状态反馈. Group chats expose 4 buttons (确认 / 添加资料 /
指派 / 稍后), private chats expose 3 (no 指派 needed since owner is the sender).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def task_card(
    *,
    plan_id: str,
    intent: str,
    plan_steps: List[Dict[str, Any]],
    owner_open_id: str = "",
    owner_name: str = "我",
    is_group_chat: bool = False,
    state_label: str = "等待确认",
    context_summary: str = "",
    missing_hints: Optional[List[str]] = None,
    progress_url: str = "",
) -> Dict[str, Any]:
    """Return a Feishu interactive card payload (cardkit / json schema)."""
    missing_hints = missing_hints or []

    # ── element 1: title bar ──
    header = {
        "title": {"tag": "plain_text", "content": "🛫 Agent-Pilot · 任务确认"},
        "template": "indigo",
    }

    # ── element 2: intent + plan ──
    plan_lines = [
        f"**📌 识别意图：** {intent[:80]}",
        "",
        f"**📋 任务计划（共 {len(plan_steps)} 步）：**",
    ]
    for i, s in enumerate(plan_steps[:8], 1):
        plan_lines.append(f"  {i}. `{s.get('tool', '')}` — {s.get('description', '')[:48]}")
    if len(plan_steps) > 8:
        plan_lines.append(f"  ...还有 {len(plan_steps) - 8} 步")

    # ── element 3: context ──
    ctx_lines = ["**🗂️ 上下文：**"]
    if context_summary:
        ctx_lines.append(context_summary)
    else:
        ctx_lines.append("（暂未读取额外资料，将基于本次输入直接生成）")
    if missing_hints:
        ctx_lines.append("")
        ctx_lines.append("**💡 建议补充：**")
        for h in missing_hints[:3]:
            ctx_lines.append(f"- {h}")

    owner_line = f"**👤 执行人：** {owner_name}（`{owner_open_id[-8:]}`）" if owner_open_id else "**👤 执行人：** 待认领"
    state_line = f"**🔄 状态：** {state_label}"

    body_md = "\n".join([
        "\n".join(plan_lines),
        "",
        "\n".join(ctx_lines),
        "",
        owner_line,
        state_line,
    ])

    # ── action buttons ──
    actions: List[Dict[str, Any]] = []
    confirm_btn = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "✅ 确认生成"},
        "type": "primary",
        "value": {"action": "task_confirm", "plan_id": plan_id},
    }
    add_btn = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "📎 添加资料"},
        "type": "default",
        "value": {"action": "task_add_context", "plan_id": plan_id},
    }
    later_btn = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "⏸ 稍后处理"},
        "type": "default",
        "value": {"action": "task_later", "plan_id": plan_id},
    }

    if is_group_chat:
        assign_btn = {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "👥 指派他人"},
            "type": "default",
            "value": {"action": "task_assign", "plan_id": plan_id},
        }
        actions = [confirm_btn, add_btn, assign_btn, later_btn]
    else:
        actions = [confirm_btn, add_btn, later_btn]

    # ── footer link ──
    progress_md = ""
    if progress_url:
        progress_md = f"**📊 进度面板：** [打开 Dashboard]({progress_url})"

    elements: List[Dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": body_md}},
        {"tag": "hr"},
        {"tag": "action", "actions": actions},
    ]
    if progress_md:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": progress_md}})

    return {
        "config": {"wide_screen_mode": True},
        "header": header,
        "elements": elements,
    }


def context_confirm_card(
    *,
    plan_id: str,
    intent: str,
    items: List[Dict[str, Any]],
    missing_hints: List[str],
    output_requirements: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The 上下文确认卡片 from PRD §7.2."""
    output_requirements = output_requirements or {}

    lines = [f"**📌 任务：** {intent[:80]}", "", "**📚 已识别上下文：**"]
    if not items:
        lines.append("- （无）")
    else:
        for it in items:
            ttl = it.get("title", "")
            kind = {"im_thread": "💬", "doc": "📄", "file": "📎", "link": "🔗", "user_note": "✍️"}.get(it.get("kind"), "•")
            lines.append(f"- {kind} {ttl}")

    if missing_hints:
        lines.append("")
        lines.append("**⚠️ Agent 建议补充：**")
        for h in missing_hints[:3]:
            lines.append(f"- {h}")

    if output_requirements:
        lines.append("")
        lines.append("**🎯 输出预期：**")
        for k, v in output_requirements.items():
            lines.append(f"- {k}: {v}")

    body_md = "\n".join(lines)

    elements: List[Dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": body_md}},
        {"tag": "hr"},
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "🚀 直接生成"},
                    "type": "primary",
                    "value": {"action": "ctx_confirm", "plan_id": plan_id},
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "📎 补充资料"},
                    "type": "default",
                    "value": {"action": "ctx_add", "plan_id": plan_id},
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "🎯 调整目标"},
                    "type": "default",
                    "value": {"action": "ctx_refine", "plan_id": plan_id},
                },
            ],
        },
    ]
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🗂️ Agent-Pilot · 上下文确认"},
            "template": "blue",
        },
        "elements": elements,
    }


def progress_card(
    *,
    plan_id: str,
    intent: str,
    steps_done: int,
    steps_total: int,
    current_step: str = "",
    artifacts: Optional[Dict[str, str]] = None,
    progress_url: str = "",
) -> Dict[str, Any]:
    """A streaming progress card that the bot updates via cardkit patches."""
    artifacts = artifacts or {}
    pct = int(steps_done / steps_total * 100) if steps_total else 0
    bar = "▰" * (pct // 10) + "▱" * (10 - pct // 10)

    lines = [
        f"**📌 任务：** {intent[:80]}",
        "",
        f"**进度：** {steps_done}/{steps_total} ({pct}%)  `{bar}`",
    ]
    if current_step:
        lines.append(f"**当前步骤：** {current_step}")
    if artifacts:
        lines.append("")
        lines.append("**📦 已生成产物：**")
        for label, url in artifacts.items():
            lines.append(f"- {label}：{url}")
    if progress_url:
        lines.append("")
        lines.append(f"**📊 实时面板：** [打开 Dashboard]({progress_url})")

    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🛰️ Agent-Pilot · 执行中"},
            "template": "carmine" if pct < 100 else "green",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}},
        ],
    }


def completion_card(
    *,
    plan_id: str,
    intent: str,
    artifacts: Dict[str, str],
    summary: str = "",
    progress_url: str = "",
) -> Dict[str, Any]:
    """Final card after the DAG finishes."""
    lines = [
        f"**🎉 任务完成：** {intent[:80]}",
        "",
    ]
    if summary:
        lines.append("**📝 内容摘要：**")
        lines.append(summary[:300])
        lines.append("")
    if artifacts:
        lines.append("**📦 产物清单：**")
        for label, url in artifacts.items():
            if not url:
                continue
            lines.append(f"- {label}：{url}")
    if progress_url:
        lines.append("")
        lines.append(f"**📊 进度面板：** [打开 Dashboard]({progress_url})")

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🛬 Agent-Pilot · 任务完成"},
            "template": "green",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🔁 再来一次"},
                        "type": "default",
                        "value": {"action": "task_replay", "plan_id": plan_id},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✏️ 微调内容"},
                        "type": "default",
                        "value": {"action": "task_refine", "plan_id": plan_id},
                    },
                ],
            },
        ],
    }


__all__ = ["task_card", "context_confirm_card", "progress_card", "completion_card"]
