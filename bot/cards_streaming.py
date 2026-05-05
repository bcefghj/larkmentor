"""Streaming-aware card templates (Feishu Card v2).

Two primary templates:

1. ``streaming_progress_card`` — used *during* generation; shows a progress bar,
   current step label, and a markdown body whose ``element_id`` is stable so the
   caller can PATCH it repeatedly (typewriter effect).

2. ``streaming_complete_card`` — swapped in when generation finishes; displays
   final content, artifact links, and action buttons.

Both produce ``schema: "2.0"`` JSON ready for ``im.v1.message.create`` (initial)
or ``im.v1.message.patch`` (incremental update).

Element IDs used (stable across patches):
  - ``stream.header``   — top-level status line
  - ``stream.bar``      — ASCII progress bar
  - ``stream.step``     — current-step label
  - ``stream.body``     — streaming markdown body (typewriter target)
  - ``stream.footer``   — timing / metadata
  - ``stream.actions``  — action button row
  - ``stream.arts``     — artifact list (complete card only)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .card_v2 import (
    _button,
    _collapsible,
    _divider,
    _envelope,
    _header,
    _text,
)


_STATUS_LABELS = {
    "planning": "📋 规划中",
    "executing": "⚙️ 执行中",
    "generating": "✍️ 生成中",
    "reviewing": "🔍 审阅中",
    "streaming": "💬 输出中",
    "complete": "✅ 已完成",
    "error": "❌ 出错",
}


def streaming_progress_card(
    title: str,
    current_text: str,
    progress_pct: float,
    status: str = "streaming",
    *,
    task_id: str = "",
    current_step: str = "",
    elapsed_sec: float = 0.0,
) -> Dict[str, Any]:
    """Card template for showing generation progress with typewriter body.

    Parameters
    ----------
    title:
        Card header title (e.g. "Agent-Pilot 执行中").
    current_text:
        Accumulated markdown text so far. Rendered in an element with
        ``element_id="stream.body"`` and ``stream: true`` for the Feishu
        cardkit.v1 typewriter effect.
    progress_pct:
        Progress 0.0–1.0.
    status:
        One of ``_STATUS_LABELS`` keys.
    task_id:
        Optional task identifier shown in footer.
    current_step:
        Human-readable label for the active step.
    elapsed_sec:
        Seconds elapsed since start, shown in footer.
    """
    pct = max(0.0, min(1.0, progress_pct))
    bar_fill = int(round(pct * 20))
    bar = "█" * bar_fill + "░" * (20 - bar_fill)
    status_label = _STATUS_LABELS.get(status, status)

    body: List[Dict[str, Any]] = [
        _text(
            f"**状态**：{status_label}  ·  进度 **{int(pct * 100)}%**",
            eid="stream.header",
        ),
        _text(f"`{bar}`", eid="stream.bar"),
    ]

    if current_step:
        body.append(_text(f"**当前步骤**：{current_step}", eid="stream.step"))

    body.append(_divider())

    body.append(
        {
            "tag": "markdown",
            "content": current_text or "▋",
            "element_id": "stream.body",
            "stream": True,
        }
    )

    footer_parts: List[str] = []
    if task_id:
        footer_parts.append(f"task: `{task_id[-8:]}`")
    if elapsed_sec > 0:
        footer_parts.append(f"耗时 {elapsed_sec:.1f}s")
    if footer_parts:
        body.append(_text("_" + "  ·  ".join(footer_parts) + "_", eid="stream.footer"))

    template = {
        "complete": "green",
        "error": "red",
    }.get(status, "blue")

    hdr = _header(title, subtitle=status_label, template=template)
    return _envelope(hdr, body)


def streaming_complete_card(
    title: str,
    content: str,
    artifacts: Optional[List[Dict[str, str]]] = None,
    actions: Optional[List[Dict[str, Any]]] = None,
    *,
    task_id: str = "",
    elapsed_sec: float = 0.0,
    summary: str = "",
) -> Dict[str, Any]:
    """Final card after streaming completes.

    Parameters
    ----------
    title:
        Card header (e.g. "Agent-Pilot 任务完成").
    content:
        Full generated content (markdown).
    artifacts:
        List of dicts with keys ``title``, ``url``, and optionally ``icon``.
    actions:
        Custom action buttons. If *None* a default set is generated.
    task_id:
        Task identifier for footer display.
    elapsed_sec:
        Total execution time.
    summary:
        Optional one-line summary above the full content.
    """
    artifacts = artifacts or []
    body: List[Dict[str, Any]] = [
        _text(
            f"**状态**：✅ 已完成  ·  耗时 **{elapsed_sec:.1f}s**",
            eid="stream.header",
        ),
    ]

    if summary:
        body.append(_text(f"_{summary[:300]}_", eid="stream.summary"))

    body.append(_divider())

    body.append(
        {
            "tag": "markdown",
            "content": content or "（无内容）",
            "element_id": "stream.body",
        }
    )

    if artifacts:
        body.append(_divider())
        arts_md = "\n".join(
            f"- {a.get('icon', '📄')} **{a.get('title', '产物')}**  [打开]({a.get('url', '#')})" for a in artifacts
        )
        body.append(_text(arts_md, eid="stream.arts"))

    body.append(_divider())

    if actions is None:
        actions = []
        if task_id:
            actions.append(
                _button("📦 归档", action="pilot.task.archive", value={"task_id": task_id}, eid="stream.btn.archive")
            )
            actions.append(
                _button("🔄 重新生成", action="pilot.task.confirm", value={"task_id": task_id}, eid="stream.btn.retry")
            )
    if actions:
        body.append(
            {
                "tag": "action",
                "actions": actions,
                "element_id": "stream.actions",
            }
        )

    footer_parts: List[str] = []
    if task_id:
        footer_parts.append(f"task: `{task_id[-8:]}`")
    footer_parts.append(f"耗时 {elapsed_sec:.1f}s")
    body.append(_text("_" + "  ·  ".join(footer_parts) + "_", eid="stream.footer"))

    hdr = _header(title, subtitle="任务完成", template="green")
    return _envelope(hdr, body)


def streaming_error_card(
    title: str,
    error_msg: str,
    *,
    task_id: str = "",
    detail: str = "",
) -> Dict[str, Any]:
    """Card shown when streaming encounters an unrecoverable error."""
    body: List[Dict[str, Any]] = [
        _text(f"**状态**：❌ 执行出错", eid="stream.header"),
        _divider(),
        _text(f"**错误**：{error_msg[:500]}", eid="stream.body"),
    ]
    if detail:
        body.append(
            _collapsible(
                "详细信息",
                _text(f"```\n{detail[:2000]}\n```", eid="stream.detail"),
                expanded=False,
                eid="stream.detail_panel",
            )
        )
    if task_id:
        body.append(_divider())
        body.append(_text(f"_task: `{task_id[-8:]}`_", eid="stream.footer"))
        body.append(
            {
                "tag": "action",
                "actions": [
                    _button(
                        "🔄 重试",
                        action="pilot.task.confirm",
                        value={"task_id": task_id},
                        style="primary",
                        eid="stream.btn.retry",
                    ),
                    _button(
                        "🙈 忽略",
                        action="pilot.task.ignore",
                        value={"task_id": task_id},
                        style="danger",
                        eid="stream.btn.ignore",
                    ),
                ],
                "element_id": "stream.actions",
            }
        )

    hdr = _header(title, subtitle="执行出错", template="red")
    return _envelope(hdr, body)


__all__ = [
    "streaming_progress_card",
    "streaming_complete_card",
    "streaming_error_card",
]
