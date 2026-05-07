"""飞书 Interactive Card 构造器（v2 标准卡片 + CardKit 2.0 增强字段）."""

from __future__ import annotations

from typing import Any


def task_suggested_card(
    *,
    task_id: str,
    title: str,
    intent: str,
    owner_display: str = "",
    plan_outline: list[str] | None = None,
    context_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """PRD §5 任务卡片（建议执行/确认/指派/添加资料/忽略）."""
    elements = [
        {"tag": "div", "text": {"tag": "lark_md",
                                "content": f"**🛫 Agent-Pilot · 任务建议**\n\n意图：{intent[:100]}"}},
        {"tag": "hr"},
    ]
    if plan_outline:
        outline_md = "\n".join(f"- {step}" for step in plan_outline[:6])
        elements.append({"tag": "div", "text": {"tag": "lark_md",
                                                "content": f"**计划概览**\n{outline_md}"}})
    if context_state:
        used = context_state.get("used", [])
        missing = context_state.get("missing", [])
        info = []
        if used:
            info.append(f"✅ 已用：{used if isinstance(used, str) else len(used)} 项")
        if missing:
            info.append(f"❓ 缺失：{', '.join(missing) if isinstance(missing, list) else missing}")
        if info:
            elements.append({"tag": "div", "text": {"tag": "lark_md",
                                                    "content": "**上下文** · " + " · ".join(info)}})
    if owner_display:
        elements.append({"tag": "div", "text": {"tag": "lark_md",
                                                "content": f"**当前 owner**：{owner_display}"}})

    elements.append({"tag": "action", "actions": [
        _btn("✅ 确认执行", "pilot.task.confirm", task_id, primary=True),
        _btn("📎 添加资料", "pilot.task.add_context", task_id),
        _btn("👤 指派他人", "pilot.task.assign", task_id),
        _btn("✋ 我来执行", "pilot.task.claim", task_id),
        _btn("🙅 忽略", "pilot.task.ignore", task_id, danger=True),
    ]})

    return {
        "header": {"title": {"tag": "plain_text", "content": f"🛫 {title or 'Agent-Pilot 任务'}"},
                   "template": "blue"},
        "elements": elements,
    }


def context_confirm_card(
    *,
    task_id: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    """PRD §7.2 上下文确认卡片（V1.5：3 按钮 + "调整目标"）."""
    used = summary.get("used", [])
    missing = summary.get("missing", [])
    task_goal = str(summary.get("task_goal", "") or "")[:120]
    task_summary = str(summary.get("task_summary", "") or "")[:120]

    elements: list[dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md",
                                "content": f"**📦 上下文确认**\n\n**已理解任务**：{task_summary or task_goal or '（无）'}"}},
        {"tag": "hr"},
    ]
    if used:
        used_md = "\n".join(f"- {u}" for u in used)
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**已用资料**\n{used_md}"}})
    else:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "**已用资料**\n_（暂无）_"}})

    if missing:
        missing_md = "\n".join(f"- {m}" for m in missing)
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**缺失资料 / 建议补充**\n{missing_md}"}})

    elements.append({"tag": "action", "actions": [
        _btn("📎 添加资料", "pilot.ctx.add", task_id),
        _btn("✅ 确认生成", "pilot.ctx.confirm", task_id, primary=True),
        _btn("📝 调整目标", "pilot.ctx.adjust", task_id),
    ]})

    return {
        "header": {"title": {"tag": "plain_text", "content": "📦 上下文确认"}, "template": "indigo"},
        "elements": elements,
    }


def task_progress_card(
    *,
    task_id: str,
    title: str = "",
    state: str = "running",
    progress: float = 0.0,
    current_step: str = "",
    streaming_content: str = "",
    element_id: str = "stream_text",
) -> dict[str, Any]:
    """流式进度卡（CardKit 2.0 streaming 用，element_id 是 patch 锚点）."""
    pct = int(progress * 100)
    bar = "▓" * (pct // 5) + "░" * (20 - pct // 5)
    elements = [
        {"tag": "div", "text": {"tag": "lark_md",
                                "content": f"**🛫 {title or 'Agent-Pilot 执行中'}**\n\n进度：`{bar}` {pct}%"}},
        {"tag": "div", "text": {"tag": "lark_md", "content": f"当前步骤：{current_step}"}},
        {"tag": "hr"},
        {
            "tag": "markdown",
            "element_id": element_id,
            "content": streaming_content or "_等待 Agent 响应..._",
        },
    ]
    return {
        "header": {"title": {"tag": "plain_text", "content": f"🛫 {title or 'Agent-Pilot'}"}, "template": "turquoise"},
        "elements": elements,
    }


def task_delivered_card(
    *,
    task_id: str,
    title: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    share_url: str = "",
) -> dict[str, Any]:
    """任务交付卡（PRD §F-13；V1.5 修复：URL 为空跳过避免 [](　) 渲染异常）."""
    elements: list[dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md",
                                "content": f"**🛬 任务完成**\n\n{title or '产物已生成'}"}},
        {"tag": "hr"},
    ]
    valid_count = 0
    for a in (artifacts or [])[:6]:
        kind = a.get("kind", "")
        url = (a.get("url") or a.get("uri") or "").strip()
        ttl = a.get("title", "") or kind
        if not url:
            continue  # 过滤空 URL，避免飞书卡片出现 [](　) 这种空链接
        valid_count += 1
        emoji = {"doc": "📄", "canvas": "🎨", "slide": "📊", "tts": "🔊"}.get(kind, "📦")
        kind_cn = {"doc": "文档", "canvas": "画布", "slide": "演示稿", "tts": "语音"}.get(kind, kind)
        elements.append({"tag": "div", "text": {"tag": "lark_md",
                                                "content": f"{emoji} **{kind_cn}** {ttl}：[打开]({url})"}})
    if valid_count == 0:
        elements.append({"tag": "div", "text": {"tag": "lark_md",
                                                "content": "_（产物列表暂时为空，请稍候或查看 dashboard 进度）_"}})

    actions: list[dict[str, Any]] = []
    if share_url:
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🔗 打开分享链接"},
            "type": "primary",
            "url": share_url,
        })
    actions.append(_btn("📁 归档", "pilot.task.archive", task_id))
    elements.append({"tag": "action", "actions": actions})

    return {
        "header": {"title": {"tag": "plain_text", "content": "🛬 Agent-Pilot · 任务完成"}, "template": "green"},
        "elements": elements,
    }


def help_card() -> dict[str, Any]:
    return {
        "header": {"title": {"tag": "plain_text", "content": "🛫 Agent-Pilot V2.0 · 智能办公助手"}, "template": "blue"},
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": (
                "**我能做什么**\n"
                "我是 AI 驱动的多 Agent 协作助手，能自动联网搜索 + 生成高质量文档和 PPT。\n\n"
                "**直接说需求即可（示例）**\n"
                "- `帮我写一份关于 AI Agent 的技术报告` → 自动生成文档\n"
                "- `做一份 8 页产品介绍 PPT` → 生成演示稿\n"
                "- `画一张系统架构图` → 画布/架构图\n"
                "- `写一份产品方案 + 架构图 + 汇报 PPT` → 三件套\n\n"
                "**工作流程**\n"
                "Planner（规划大纲）→ Researcher（联网搜索数据）→ Writer（撰写内容）→ Reviewer（质量检查）→ 交付\n\n"
                "**命令**\n"
                "- `帮助` 显示本卡片\n"
                "- `状态` 查看当前任务进度\n"
                "- `/pilot <需求>` 强制触发任务\n\n"
                "💡 说的越具体（主题 + 受众 + 页数），生成质量越高"
            )}},
        ],
    }


def outline_confirm_card(
    *,
    task_id: str,
    title: str,
    outline: list[dict[str, Any]],
) -> dict[str, Any]:
    """Human-in-the-Loop 大纲确认卡片（Approve / Revise / Cancel）."""
    elements: list[dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md",
                                "content": "**Agent-Pilot 已为您规划了以下结构：**"}},
        {"tag": "hr"},
    ]
    for idx, section in enumerate(outline, 1):
        heading = section.get("heading", "")
        key_points = section.get("key_points") or []
        points_md = "\n".join(f"  - {pt}" for pt in key_points)
        section_md = f"**{idx}. {heading}**"
        if points_md:
            section_md += f"\n{points_md}"
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": section_md}})

    elements.append({"tag": "hr"})
    elements.append({"tag": "div", "text": {"tag": "lark_md",
                                            "content": "_确认后 Agent 将开始联网搜索 + 撰写内容_"}})
    elements.append({"tag": "action", "actions": [
        _btn("✅ 确认生成", "pilot.outline.confirm", task_id, primary=True),
        _btn("✏️ 修改大纲", "pilot.outline.revise", task_id),
        _btn("❌ 取消任务", "pilot.outline.cancel", task_id, danger=True),
    ]})

    return {
        "header": {"title": {"tag": "plain_text", "content": f"📋 大纲确认 · {title}"},
                   "template": "blue"},
        "elements": elements,
    }


def first_time_welcome_card() -> dict[str, Any]:
    return {
        "header": {"title": {"tag": "plain_text", "content": "👋 欢迎使用 Agent-Pilot V1"}, "template": "blue"},
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": (
                "你好！👋 我是 **Agent-Pilot V1**，飞书 IM 中的 AI 主驾驶。\n\n"
                "我可以把你的「群聊讨论 → 文档 → 画布 → PPT + 演讲稿」压缩到 **90 秒** 一键交付。\n\n"
                "试试用自然语言告诉我你要做什么："
            )}},
            {"tag": "div", "text": {"tag": "lark_md", "content": (
                "- 📄 `帮我写一份 AI Agent 趋势报告`\n"
                "- 📊 `做一份 8 页客户汇报 PPT`\n"
                "- 🎨 `画一张产品架构图`\n"
                "- ⭐ `产品方案 + 架构图 + 评审 PPT 三件套`"
            )}},
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "📖 查看帮助"},
                 "value": {"action": "pilot.help"}, "type": "primary"},
            ]},
        ],
    }


# ── helpers ──


def _btn(label: str, action: str, task_id: str, *, primary: bool = False, danger: bool = False) -> dict[str, Any]:
    btn: dict[str, Any] = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "value": {"action": action, "task_id": task_id},
    }
    if primary:
        btn["type"] = "primary"
    elif danger:
        btn["type"] = "danger"
    return btn
