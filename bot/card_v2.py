"""Feishu Card JSON 2.0 builder (P2.4).

Why a new module
----------------

The existing ``bot/card_builder.py`` emits v1 schema (``{"config":..., "header":..., "elements":[...]}``)
which the Feishu client renders as "static" cards. The 2026 Feishu platform adds:

- ``schema: "2.0"`` — opt-in to the new renderer
- ``behaviors[]`` on interactive elements — combine jump + callback in one button
- ``element_id`` — the Agent can patch a specific element without rebuilding the card
- ``form`` containers — native submit/reset without a custom webhook
- ``collapsible_panel`` — long plans collapse, saving vertical space in IM

We keep ``card_builder.py`` intact for backward compatibility with Shield/Mentor
cards, and add progress / plan / skills cards used by Agent-Pilot.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


# ── primitives ────────────────────────────────────────────────────────────────


def _header(title: str, subtitle: str = "", template: str = "blue") -> Dict[str, Any]:
    hdr: Dict[str, Any] = {
        "title": {"tag": "plain_text", "content": title},
        "template": template,
    }
    if subtitle:
        hdr["subtitle"] = {"tag": "plain_text", "content": subtitle}
    return hdr


def _text(content: str, *, eid: str = "", tag: str = "markdown") -> Dict[str, Any]:
    block: Dict[str, Any] = {"tag": tag, "content": content}
    if eid:
        block["element_id"] = eid
    return block


def _button(label: str, *, action: str = "", url: str = "",
            form_action: str = "",
            value: Optional[Dict[str, Any]] = None,
            style: str = "default",
            eid: str = "") -> Dict[str, Any]:
    """v2 button with behaviors[] — supports simultaneous open_url + callback."""
    behaviors: List[Dict[str, Any]] = []
    if url:
        behaviors.append({
            "type": "open_url",
            "default_url": url,
            "pc_url": url, "ios_url": url, "android_url": url,
        })
    if action:
        behaviors.append({
            "type": "callback",
            "value": {"action": action, **(value or {})},
        })
    if form_action:
        behaviors.append({"type": form_action})
    btn: Dict[str, Any] = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": style,
        "behaviors": behaviors or [{"type": "callback",
                                    "value": {"action": action or "noop",
                                              **(value or {})}}],
    }
    if eid:
        btn["element_id"] = eid
    return btn


def _divider() -> Dict[str, Any]:
    return {"tag": "hr"}


def _columns(*cols: Dict[str, Any], ratio: str = "auto") -> Dict[str, Any]:
    return {
        "tag": "column_set",
        "horizontal_spacing": "8px",
        "flex_mode": ratio if ratio in {"none", "stretch", "flow", "bisect"} else "stretch",
        "columns": list(cols),
    }


def _column(*elements: Dict[str, Any], weight: int = 1) -> Dict[str, Any]:
    return {
        "tag": "column",
        "weight": weight,
        "vertical_spacing": "6px",
        "elements": list(elements),
    }


def _collapsible(label: str, *elements: Dict[str, Any],
                 expanded: bool = False,
                 eid: str = "") -> Dict[str, Any]:
    panel: Dict[str, Any] = {
        "tag": "collapsible_panel",
        "expanded": expanded,
        "background_style": "grey",
        "header": {
            "title": {"tag": "markdown", "content": f"**{label}**"},
            "icon_expanded_angle": 180,
        },
        "elements": list(elements),
    }
    if eid:
        panel["element_id"] = eid
    return panel


def _envelope(header: Dict[str, Any],
              elements: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Wrap header + elements in the schema=2.0 top-level structure."""
    return {
        "schema": "2.0",
        "config": {
            "streaming_mode": True,
            "summary": {"content": header.get("title", {}).get("content", "")},
            "width_mode": "fill",
        },
        "card_link": None,
        "header": header,
        "body": {
            "direction": "vertical",
            "padding": "12px",
            "elements": elements,
        },
    }


# ── Pilot / Agent cards ───────────────────────────────────────────────────────


_STATUS_BADGE = {
    "pending": "⏳ 待执行",
    "running": "🛫 执行中",
    "success": "✅ 完成",
    "failed": "❌ 失败",
    "skipped": "⏭️ 跳过",
}


def pilot_progress_card(
    *,
    plan_id: str,
    intent: str,
    steps: Iterable[Dict[str, Any]],
    status: str = "running",
    progress: float = 0.0,
    dashboard_url: str = "",
    share_url: str = "",
    deliverables: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """The live progress card for /pilot plans.

    ``element_id`` values are stable so the Agent can patch them via
    ``im.v1.message.patch`` without rebuilding the full card.

    - ``pilot.progress`` — top status text
    - ``pilot.bar``      — progress bar
    - ``pilot.steps``    — the step list markdown
    - ``pilot.delivs``   — deliverables block
    """
    bar_fill = int(min(20, max(0, round(progress * 20))))
    bar = "█" * bar_fill + "░" * (20 - bar_fill)

    step_lines: List[str] = []
    for i, s in enumerate(steps, 1):
        name = s.get("name") or s.get("tool") or f"step-{i}"
        stat = _STATUS_BADGE.get(s.get("status", "pending"), "⏳")
        note = s.get("note") or s.get("summary") or ""
        step_lines.append(f"{i}. **{name}** — {stat}" + (f" · {note[:60]}" if note else ""))

    body: List[Dict[str, Any]] = [
        _text(f"**意图**：{intent[:200]}", eid="pilot.intent"),
        _text(f"**状态**：{_STATUS_BADGE.get(status, status)}  ·  进度 {int(progress*100)}%",
              eid="pilot.progress"),
        _text(f"`{bar}`", eid="pilot.bar"),
        _divider(),
        _collapsible("执行步骤（点击展开）",
                     _text("\n".join(step_lines) or "（待规划）", eid="pilot.steps"),
                     expanded=status == "running"),
    ]

    if deliverables:
        deliv_md = "\n".join(
            f"- [{d.get('label','产物')}]({d.get('url','')})"
            + (f" · {d.get('note','')}" if d.get("note") else "")
            for d in deliverables
        )
        body.append(_divider())
        body.append(_text("**交付物**\n" + deliv_md, eid="pilot.delivs"))

    btns: List[Dict[str, Any]] = []
    if dashboard_url:
        btns.append(_button("实时进度", url=dashboard_url, style="primary"))
    if share_url:
        btns.append(_button("分享链接", url=share_url, action="pilot_copy_share",
                            value={"plan_id": plan_id}))
    btns.append(_button("重新规划", action="pilot_replan", value={"plan_id": plan_id},
                        style="default"))
    btns.append(_button("取消", action="pilot_cancel", value={"plan_id": plan_id},
                        style="danger"))

    body.append(_divider())
    body.append({"tag": "action", "actions": btns, "element_id": "pilot.actions"})

    color = {"running": "blue", "success": "green",
             "failed": "red", "pending": "grey",
             "skipped": "orange"}.get(status, "blue")
    header = _header(
        "Agent-Pilot 执行中" if status == "running" else f"Agent-Pilot {_STATUS_BADGE.get(status, status)}",
        subtitle=f"plan_id: {plan_id}",
        template=color,
    )
    return _envelope(header, body)


def pilot_patch_progress(
    *,
    status: str,
    progress: float,
    step_summary: str = "",
    deliverables_md: str = "",
) -> Dict[str, Dict[str, Any]]:
    """Return a minimal patch payload addressed by ``element_id``.

    The caller sends this via ``im.v1.message.patch`` to update an already
    posted progress card in-place. Keys map 1:1 to the eids used above.
    """
    bar_fill = int(min(20, max(0, round(progress * 20))))
    bar = "█" * bar_fill + "░" * (20 - bar_fill)
    patches: Dict[str, Dict[str, Any]] = {
        "pilot.progress": _text(
            f"**状态**：{_STATUS_BADGE.get(status, status)}  ·  进度 {int(progress*100)}%",
            eid="pilot.progress"),
        "pilot.bar": _text(f"`{bar}`", eid="pilot.bar"),
    }
    if step_summary:
        patches["pilot.steps"] = _text(step_summary, eid="pilot.steps")
    if deliverables_md:
        patches["pilot.delivs"] = _text("**交付物**\n" + deliverables_md,
                                        eid="pilot.delivs")
    return patches


# ── Skills / Context cards (evaluator wow points) ─────────────────────────────


def skills_list_card(skills: List[Dict[str, Any]]) -> Dict[str, Any]:
    lines: List[str] = []
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for s in skills:
        by_source.setdefault(s.get("source", "other"), []).append(s)
    for src, bucket in sorted(by_source.items()):
        lines.append(f"\n**{src}**  ·  {len(bucket)} 个")
        for s in sorted(bucket, key=lambda x: x.get("name", "")):
            lines.append(f"- `{s.get('name','?')}` — {(s.get('description','') or '')[:70]}")
    body = [
        _text(f"共挂载 **{len(skills)}** 个 Skills（三层渐进披露）", eid="skills.total"),
        _divider(),
        _text("\n".join(lines) or "（暂无）", eid="skills.body"),
    ]
    return _envelope(_header("Skills 清单", template="indigo"), body)


def context_card(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    tokens = snapshot.get("tokens", 0)
    budget = snapshot.get("budget", 1)
    pct = min(1.0, tokens / max(1, budget))
    bar_fill = int(min(20, max(0, round(pct * 20))))
    bar = "█" * bar_fill + "░" * (20 - bar_fill)
    layer = snapshot.get("layer", "L0")
    events = snapshot.get("recent_events") or []
    body = [
        _text(f"**Token 预算**：{tokens} / {budget}  ·  {int(pct*100)}%",
              eid="ctx.tokens"),
        _text(f"`{bar}`", eid="ctx.bar"),
        _text(f"**当前压缩层级**：{layer}", eid="ctx.layer"),
        _divider(),
        _collapsible("最近 20 条事件",
                     _text("\n".join(f"- {e}" for e in events[-20:]) or "（无）",
                           eid="ctx.events"),
                     expanded=False),
    ]
    return _envelope(_header("Context 快照", template="turquoise"), body)


def clarify_card(question: str, options: List[str],
                 *, clarify_id: str = "") -> Dict[str, Any]:
    """AskUserQuestion card used when ambiguity is too high to proceed."""
    buttons = [
        _button(opt, action="pilot_clarify",
                value={"option": opt, "clarify_id": clarify_id},
                style="primary" if i == 0 else "default")
        for i, opt in enumerate(options[:4])
    ]
    buttons.append(_button("输入其它", action="pilot_clarify_custom",
                           value={"clarify_id": clarify_id}))
    body = [
        _text(f"**Pilot 需要你澄清一下**\n\n{question}", eid="clarify.q"),
        _divider(),
        {"tag": "action", "actions": buttons, "element_id": "clarify.actions"},
    ]
    return _envelope(_header("需要澄清", template="yellow"), body)
