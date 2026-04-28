"""Pilot 任务卡片家族 (PRD §5.4 + §6.3 + §7.2 + 多 agent 可视化).

四类卡片：
1. ``task_suggested_card``  PRD §5.4 任务识别卡：5 按钮 + 上下文状态 + owner
2. ``assign_picker_card``   PRD §6.3 指派群成员选择器
3. ``context_confirm_card`` PRD §7.2 上下文确认卡（已用/缺失/建议补充）
4. ``multi_agent_card``     5 named agents 协同实时可视化
5. ``task_progress_card``   cardkit.v1 流式打字机进度（接 OrchestratorService 事件）
6. ``task_delivered_card``  PRD §15.2 完成卡（artifact 链接 + 归档）
7. ``task_clarify_card``    PRD §5 信息不足时弹的澄清卡

每张卡的 element_id 都稳定，方便 ``im.v1.message.patch`` 实时增量更新而不
重建整张卡片（这是 cardkit.v1 流式 wow #1 的核心）。

构造结果 JSON 直接发给飞书 API（schema 2.0）。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .card_v2 import (
    _button,
    _collapsible,
    _columns,
    _column,
    _divider,
    _envelope,
    _header,
    _text,
)


# ── 1. PRD §5.4 任务识别卡 ──────────────────────────────────────────────────


def task_suggested_card(
    *,
    task_id: str,
    title: str,
    intent: str,
    source_chat: str = "",
    owner_open_id: str = "",
    owner_display: str = "",
    plan_outline: Optional[List[str]] = None,
    context_state: Optional[Dict[str, Any]] = None,
    detail_url: str = "",
) -> Dict[str, Any]:
    """PRD §5.4 任务卡片完整版.

    必备：
    - 识别摘要（任务名 + 来源对话 + 初步目标）
    - 任务计划（拆解的子任务）
    - 上下文状态（已用 / 缺失 / 建议）
    - 执行人显示
    - 5 按钮：确认生成 / 添加资料 / 指派他人 / 查看详情 / 忽略
    - 状态反馈（执行中 / 已完成 / 等待确认 / 失败）

    ``context_state`` 期望 keys: ``used`` (int), ``missing`` (List[str]), ``suggested`` (List[str])
    """
    plan_outline = plan_outline or []
    context_state = context_state or {}

    body: List[Dict[str, Any]] = [
        _text(f"**🎯 任务识别**：{title}", eid="pilot.task.title"),
    ]
    if intent and intent != title:
        body.append(_text(f"_「{intent[:160]}」_", eid="pilot.task.intent"))
    body.append(_text(
        f"**来源**：{source_chat or '当前对话'}  ·  **执行人**：{owner_display or '待选择'}",
        eid="pilot.task.meta",
    ))
    body.append(_divider())

    # 任务计划
    if plan_outline:
        plan_md = "\n".join(f"{i+1}. {p}" for i, p in enumerate(plan_outline[:6]))
    else:
        plan_md = "_等待 owner 确认后开始规划_"
    body.append(_collapsible(
        "任务计划（点击展开）",
        _text(plan_md, eid="pilot.task.plan"),
        expanded=bool(plan_outline),
        eid="pilot.task.plan_panel",
    ))
    body.append(_divider())

    # 上下文状态
    used = context_state.get("used", 0)
    missing = context_state.get("missing", []) or []
    suggested = context_state.get("suggested", []) or []
    ctx_md = f"📦 已识别可用资料 **{used}** 条"
    if missing:
        ctx_md += "\n" + "❓ 缺失：" + "、".join(missing[:4])
    if suggested:
        ctx_md += "\n" + "💡 建议补充：" + "、".join(suggested[:4])
    body.append(_text(ctx_md, eid="pilot.task.ctx"))
    body.append(_divider())

    # 5 按钮（PRD §5.4）
    btns = [
        _button("✅ 确认生成", action="pilot.task.confirm",
                value={"task_id": task_id}, style="primary",
                eid="pilot.btn.confirm"),
        _button("📎 添加资料", action="pilot.task.add_context",
                value={"task_id": task_id}, eid="pilot.btn.add_ctx"),
        _button("👤 指派他人", action="pilot.task.assign",
                value={"task_id": task_id}, eid="pilot.btn.assign"),
    ]
    if detail_url:
        btns.append(_button("🔍 查看详情", url=detail_url, eid="pilot.btn.detail"))
    btns.append(_button("🙈 忽略", action="pilot.task.ignore",
                        value={"task_id": task_id},
                        style="danger", eid="pilot.btn.ignore"))
    body.append({
        "tag": "action",
        "actions": btns,
        "element_id": "pilot.task.actions",
    })

    body.append(_text(
        f"_task_id: `{task_id}`  ·  _建议由 Agent-Pilot 主动识别，可忽略_",
        eid="pilot.task.footer",
    ))

    header = _header(
        "Agent-Pilot · 任务建议",
        subtitle=f"等待 owner 确认  ·  task: {task_id[-8:]}",
        template="indigo",
    )
    return _envelope(header, body)


# ── 2. PRD §6.3 指派群成员选择器卡 ───────────────────────────────────────────


def assign_picker_card(
    *,
    task_id: str,
    candidates: List[Dict[str, str]],
    current_owner_open_id: str = "",
) -> Dict[str, Any]:
    """PRD §6.3 指派他人 → 群成员选择器.

    ``candidates`` items: ``{"open_id": "...", "name": "..."}``
    """
    body: List[Dict[str, Any]] = [
        _text(f"**👥 选择执行人**  ·  task: `{task_id[-8:]}`", eid="pilot.assign.title"),
    ]
    if current_owner_open_id:
        body.append(_text(f"_当前 owner: `{current_owner_open_id[-6:]}`_",
                          eid="pilot.assign.curr"))
    body.append(_divider())

    # 候选列表
    rows: List[Dict[str, Any]] = []
    for c in candidates[:12]:
        oid = c.get("open_id", "")
        name = c.get("name") or oid[-6:] or "?"
        rows.append(_columns(
            _column(_text(f"@{name}"), weight=3),
            _column(
                _button(f"指派给 {name}",
                         action="pilot.task.assign_to",
                         value={"task_id": task_id, "to_open_id": oid},
                         style="primary",
                         eid=f"pilot.assign.btn.{oid[-6:]}"),
                weight=2,
            ),
        ))
    body.extend(rows)

    body.append(_divider())
    body.append({
        "tag": "action",
        "actions": [
            _button("👋 我来执行", action="pilot.task.claim_self",
                    value={"task_id": task_id}, style="primary",
                    eid="pilot.assign.btn.claim_self"),
            _button("取消", action="pilot.task.assign_cancel",
                    value={"task_id": task_id}, eid="pilot.assign.btn.cancel"),
        ],
        "element_id": "pilot.assign.actions",
    })

    return _envelope(_header("指派任务执行人", subtitle="PRD §6.3", template="green"), body)


# ── 3. PRD §7.2 上下文确认卡 ──────────────────────────────────────────────────


def context_confirm_card(
    *,
    task_id: str,
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    """PRD §7.2 上下文确认卡（已用 / 缺失 / 建议补充三段式）.

    ``summary`` 对应 ``ContextService.render_confirm_summary(cp)`` 输出.
    """
    used_text = (
        f"📚 IM 消息 **{summary.get('msg_count', 0)}** 条"
        f"  ·  关联文档 **{summary.get('doc_count', 0)}** 份"
        f"  ·  用户补充 **{summary.get('user_material_count', 0)}** 项"
        f"  ·  共 **{summary.get('total_chars', 0)}** 字符"
    )
    missing = summary.get("missing", []) or []
    miss_text = "❓ " + ("、".join(missing[:4]) if missing else "无 — 信息已满足")

    body: List[Dict[str, Any]] = [
        _text(f"**📦 即将使用的资料**  ·  task: `{task_id[-8:]}`",
              eid="pilot.ctx.header"),
        _text(used_text, eid="pilot.ctx.used"),
        _divider(),
        _text("**🔍 缺失信息（PRD §7.2）**", eid="pilot.ctx.missing.label"),
        _text(miss_text, eid="pilot.ctx.missing"),
        _divider(),
    ]

    # 输出意图
    out_md = (
        f"📤 **输出形式**：{summary.get('output_primary', 'doc')}  "
        f"·  **受众**：{summary.get('output_audience') or '未指定'}  "
        f"·  **风格**：{summary.get('output_style') or '默认'}"
    )
    body.append(_text(out_md, eid="pilot.ctx.output"))

    if summary.get("must_cite"):
        body.append(_text("✓ 启用 Citation Agent · 每条 claim 自动标 source",
                          eid="pilot.ctx.cite"))
    body.append(_divider())

    # 操作
    can_proceed = bool(summary.get("has_min_info"))
    body.append({
        "tag": "action",
        "actions": [
            _button(("✅ 确认生成" if can_proceed else "⚠ 信息不足，仍要生成"),
                    action="pilot.ctx.confirm",
                    value={"task_id": task_id},
                    style="primary" if can_proceed else "default",
                    eid="pilot.ctx.btn.confirm"),
            _button("📎 继续添加资料", action="pilot.ctx.add_more",
                    value={"task_id": task_id}, eid="pilot.ctx.btn.add"),
            _button("⏸ 暂停", action="pilot.task.pause",
                    value={"task_id": task_id}, eid="pilot.ctx.btn.pause"),
        ],
        "element_id": "pilot.ctx.actions",
    })

    template = "green" if can_proceed else "orange"
    return _envelope(_header("上下文确认", subtitle="PRD §7.2", template=template), body)


# ── 4. 多 agent 协同实时可视化卡 ──────────────────────────────────────────────


_AGENT_BADGES = {
    "@pilot": ("🛫", "blue"),
    "@researcher": ("🔍", "indigo"),
    "@debater": ("⚖️", "purple"),
    "@validator": ("🔬", "green"),
    "@citation": ("📑", "yellow"),
    "@mentor": ("✍️", "teal"),
    "@shield": ("🛡️", "red"),
}


def multi_agent_card(
    *,
    task_id: str,
    pipeline_id: str = "",
    transcripts: List[Dict[str, Any]] = None,
    quality_gates_passed: int = 0,
    quality_gates_total: int = 0,
    quality_score: float = 0.0,
    citations_total: int = 0,
    citations_verified: int = 0,
    safety_blocked: bool = False,
    overall_ok: Optional[bool] = None,
) -> Dict[str, Any]:
    """5 named agents 协同进度卡."""
    transcripts = transcripts or []

    rows: List[str] = []
    for ts in transcripts:
        agent = ts.get("agent", "?")
        emoji, _ = _AGENT_BADGES.get(agent, ("•", "default"))
        ok = ts.get("ok", True)
        summary = (ts.get("summary") or "")[:80]
        ms = ts.get("duration_ms", 0)
        flag = "✅" if ok else "❌"
        rows.append(f"{emoji} **{agent}** {flag} `{ms}ms` · {summary}")

    body: List[Dict[str, Any]] = [
        _text(f"**🤖 多 Agent 协同**  ·  task: `{task_id[-8:]}`  ·  pipeline: `{pipeline_id[-8:]}`",
              eid="pilot.ma.header"),
        _divider(),
        _text("\n".join(rows) or "_等待启动_", eid="pilot.ma.transcripts"),
        _divider(),
    ]

    # 关键指标
    if quality_gates_total > 0:
        bar = "█" * int(quality_score * 10) + "░" * max(0, 10 - int(quality_score * 10))
        body.append(_text(
            f"**5 Quality Gates**：{quality_gates_passed}/{quality_gates_total}  "
            f"`{bar}`  {int(quality_score * 100)}%",
            eid="pilot.ma.quality",
        ))
    if citations_total > 0:
        body.append(_text(
            f"**Citation**：{citations_verified}/{citations_total} verified",
            eid="pilot.ma.citation",
        ))
    if safety_blocked:
        body.append(_text("🚨 **@shield: 安全审查未通过**", eid="pilot.ma.safety"))
    elif overall_ok:
        body.append(_text("✅ **整体审查通过**", eid="pilot.ma.overall"))

    template = "red" if safety_blocked else ("green" if overall_ok else "blue")
    return _envelope(_header("多 Agent 协同实时", subtitle=pipeline_id[:16], template=template), body)


# ── 5. cardkit.v1 流式打字机进度 ──────────────────────────────────────────────


def task_progress_card(
    *,
    task_id: str,
    state: str = "planning",
    progress: float = 0.0,
    current_step: str = "",
    streaming_content: str = "",
) -> Dict[str, Any]:
    bar_fill = int(min(20, max(0, round(progress * 20))))
    bar = "█" * bar_fill + "░" * (20 - bar_fill)
    body: List[Dict[str, Any]] = [
        _text(f"**🛫 任务执行**  ·  task: `{task_id[-8:]}`  ·  状态：{state}",
              eid="pilot.prog.header"),
        _text(f"`{bar}`  {int(progress * 100)}%", eid="pilot.prog.bar"),
        _divider(),
        _text(f"**当前步骤**：{current_step or '_等待规划_'}", eid="pilot.prog.step"),
        # cardkit.v1 流式打字机：stream:True 让飞书逐字渲染
        {
            "tag": "markdown",
            "content": streaming_content or "▋",
            "element_id": "pilot.prog.stream",
            "stream": True,
        },
    ]
    return _envelope(_header("Agent-Pilot 执行中", subtitle="cardkit.v1 流式", template="blue"), body)


# ── 6. PRD §15.2 完成卡 ───────────────────────────────────────────────────────


def task_delivered_card(
    *,
    task_id: str,
    title: str,
    artifacts: List[Dict[str, str]],
    share_url: str = "",
    summary: str = "",
) -> Dict[str, Any]:
    body: List[Dict[str, Any]] = [
        _text(f"**🎉 任务已完成**  ·  {title}", eid="pilot.done.title"),
    ]
    if summary:
        body.append(_text(f"_{summary[:300]}_", eid="pilot.done.summary"))
    body.append(_divider())

    arts_md = "\n".join(
        f"- {a.get('icon', '📄')} **{a.get('title', '产物')}** "
        f"[打开]({a.get('url', '#')})"
        for a in artifacts
    )
    body.append(_text(arts_md or "_无产出_", eid="pilot.done.arts"))
    body.append(_divider())

    actions = []
    if share_url:
        actions.append(_button("🔗 分享链接", url=share_url, eid="pilot.done.btn.share",
                                style="primary"))
    actions.append(_button("📦 归档", action="pilot.task.archive",
                            value={"task_id": task_id}, eid="pilot.done.btn.archive"))
    actions.append(_button("🔄 继续生成 PPT", action="pilot.task.request_ppt",
                            value={"task_id": task_id}, eid="pilot.done.btn.ppt"))
    body.append({"tag": "action", "actions": actions, "element_id": "pilot.done.actions"})

    return _envelope(_header("交付完成", template="green"), body)


# ── 7. PRD §5 信息不足澄清卡 ─────────────────────────────────────────────────


def task_clarify_card(
    *,
    task_id: str,
    questions: List[str],
    detected_goal: str = "",
) -> Dict[str, Any]:
    body: List[Dict[str, Any]] = [
        _text(f"**🤔 Agent 需要更多信息**  ·  task: `{task_id[-8:]}`",
              eid="pilot.clar.header"),
    ]
    if detected_goal:
        body.append(_text(f"识别到的初步目标：「{detected_goal[:100]}」",
                          eid="pilot.clar.goal"))
    body.append(_divider())

    qs_md = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions[:3]))
    body.append(_text(qs_md or "_暂无澄清问题_", eid="pilot.clar.qs"))
    body.append(_divider())

    body.append({
        "tag": "action",
        "actions": [
            _button("✏️ 在对话中回答", action="pilot.task.clarify_inline",
                     value={"task_id": task_id}, style="primary",
                     eid="pilot.clar.btn.inline"),
            _button("跳过澄清直接生成", action="pilot.task.confirm",
                     value={"task_id": task_id, "skip_clarify": True},
                     eid="pilot.clar.btn.skip"),
            _button("🙈 忽略", action="pilot.task.ignore",
                     value={"task_id": task_id}, style="danger",
                     eid="pilot.clar.btn.ignore"),
        ],
        "element_id": "pilot.clar.actions",
    })
    return _envelope(_header("澄清任务意图", subtitle="PRD §5", template="orange"), body)


__all__ = [
    "task_suggested_card",
    "assign_picker_card",
    "context_confirm_card",
    "multi_agent_card",
    "task_progress_card",
    "task_delivered_card",
    "task_clarify_card",
]
