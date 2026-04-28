"""Recovery Card · 双线 UI 唯一交点 (LarkMentor v2)

Recovery Card 是 LarkMentor 双线产品（消息层守护 + 表达层带教）在 UI 上
唯一的真合体点。当用户结束 focus / 退出勿扰 / 回到工位时，Bot 弹出一张
卡片，**上半张是 Smart Shield 的产物，下半张是 Mentor 的产物**：

  ┌──────────────────────────────────────────────────────┐
  │ 🛡 LarkMentor · 上下文恢复 · 你专注了 45 分钟        │
  ├──────────────────────────────────────────────────────┤
  │ 上半张 · 我替你挡了什么（按重要性排序）               │
  │   • [P0] 张三 · 5 分钟前 · "紧急：方案需要确认"      │
  │   • [P1] 李四 · 3 分钟前 · "今天能给我反馈吗"        │
  │   • [P2] 工程群 · 10 分钟前 · "周五的会议改到三点"  │
  ├──────────────────────────────────────────────────────┤
  │ 下半张 · 我替你起草了对最高优先级消息的回复          │
  │   ┌─ v1 保守 ───────────────────────────────────┐   │
  │   │ 收到，我刚回到工位，看一下方案后立刻回您。   │   │
  │   └──────────────────────────────────────────────┘   │
  │   ┌─ v2 中性 ───────────────────────────────────┐   │
  │   │ 张哥，方案我还没细看，下午 2 点前给到你。    │   │
  │   └──────────────────────────────────────────────┘   │
  │   ┌─ v3 直接 ───────────────────────────────────┐   │
  │   │ 已收到，下午 2 点前回复。                    │   │
  │   └──────────────────────────────────────────────┘   │
  ├──────────────────────────────────────────────────────┤
  │ [采纳 v1] [采纳 v2] [采纳 v3] [全部忽略] [详情]      │
  │ 🤖 LarkMentor · 30 秒内可点撤回 · 永不自动发送        │
  └──────────────────────────────────────────────────────┘

设计原则（详见 ../ARCHITECTURE.md §2 原则 3 合体点 2）：

* 上下两半在同一张卡片，不允许拆成两条消息——这是"双线"的视觉证据。
* 草稿永远 3 版（保守/中性/直接），用户点"采纳"只复制不发送。
* 起草仅基于"最高优先级消息"，避免为每条都起草浪费 token。
* 卡片底部固定标识 + 30 秒撤回按钮——合规底线（草稿不发送）。

数据来源：

* 上半张 → ``core.flow_memory.working`` 的 since_ts 之后的"挡掉"事件
* 下半张 → ``core.mentor.mentor_write.draft_reply`` 对最高优先级消息

调用入口：

* ``core.bot.event_handler`` 在用户 ``focus_end`` 时调用 ``send_recovery_card``
* MCP 工具 ``recovery.build`` 也暴露此能力
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("larkmentor.recovery_card")


# ── 数据结构 ─────────────────────────────────────────────────


@dataclass
class BlockedMessage:
    """A message that Smart Shield held back during the focus session."""

    sender_name: str
    sender_id: str
    content: str
    level: str        # "P0" | "P1" | "P2" | "P3"
    score: float
    ts: int
    chat_name: str = ""
    message_id: str = ""

    def short_content(self, n: int = 50) -> str:
        c = self.content.strip()
        return c if len(c) <= n else c[:n] + "..."

    def relative_time(self, now_ts: Optional[int] = None) -> str:
        now = now_ts or int(time.time())
        delta = now - self.ts
        if delta < 60:
            return f"{delta} 秒前"
        if delta < 3600:
            return f"{delta // 60} 分钟前"
        if delta < 86400:
            return f"{delta // 3600} 小时前"
        return f"{delta // 86400} 天前"


@dataclass
class DraftReply:
    """One version of an AI-suggested reply draft."""

    tone: str         # "conservative" | "neutral" | "direct"
    label: str        # "保守" | "中性" | "直接"
    text: str
    citation: str = ""    # 召回的 KB chunk source（如有）

    def to_card_value(self) -> str:
        """Encode for Feishu card button value field."""
        return f"adopt:{self.tone}"


@dataclass
class RecoveryContext:
    """Aggregated input to build a Recovery Card."""

    user_open_id: str
    focus_duration_sec: int
    period_summary: Dict[str, int] = field(default_factory=dict)
    blocked: List[BlockedMessage] = field(default_factory=list)
    drafts_for_top: List[DraftReply] = field(default_factory=list)
    top_message: Optional[BlockedMessage] = None
    explanation: str = ""


# ── 数据收集 ────────────────────────────────────────────────


def collect_blocked_messages(
    user_open_id: str,
    since_ts: int,
    *,
    max_n: int = 5,
) -> List[BlockedMessage]:
    """从 working_memory 拉 since_ts 之后的"挡掉"事件，按优先级排序。"""
    try:
        from core.flow_memory.working import WorkingMemory
        wm = WorkingMemory.load(user_open_id)
        events = wm.since(since_ts)
    except Exception as e:
        logger.warning("collect_blocked: load wm failed: %s", e)
        return []

    blocked: List[BlockedMessage] = []
    for ev in events:
        if ev.kind != "message":
            continue
        p = ev.payload or {}
        level = p.get("level", "P3")
        if level == "P3":
            continue
        blocked.append(BlockedMessage(
            sender_name=p.get("sender_name", "未知"),
            sender_id=p.get("sender_id", ""),
            content=p.get("content", ""),
            level=level,
            score=float(p.get("score", 0.0)),
            ts=ev.ts,
            chat_name=p.get("chat_name", ""),
            message_id=p.get("message_id", ""),
        ))

    level_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    blocked.sort(key=lambda m: (level_order.get(m.level, 9), -m.ts))
    return blocked[:max_n]


def pick_top_message(blocked: List[BlockedMessage]) -> Optional[BlockedMessage]:
    """Return the highest-priority message worth drafting a reply for."""
    if not blocked:
        return None
    return blocked[0]


def draft_three_versions(
    user_open_id: str,
    msg: BlockedMessage,
) -> List[DraftReply]:
    """Generate 3 tone versions for the top message via mentor_write.

    Falls back to template strings when the LLM call is unavailable
    (offline mode / quota exhausted), so Recovery Card never blocks.
    """
    drafts: List[DraftReply] = []
    try:
        from core.mentor.mentor_write import draft_three_tones
        out = draft_three_tones(
            user_open_id=user_open_id,
            sender_name=msg.sender_name,
            content=msg.content,
        )
        for tone, label, text, cite in out:
            drafts.append(DraftReply(tone=tone, label=label, text=text, citation=cite))
        if drafts:
            return drafts
    except Exception as e:
        logger.info("draft_three_tones unavailable, falling back: %s", e)

    drafts = [
        DraftReply(
            tone="conservative",
            label="保守",
            text=f"收到，我刚回到工位，看一下后立刻回复 {msg.sender_name}。",
        ),
        DraftReply(
            tone="neutral",
            label="中性",
            text=f"{msg.sender_name}，我刚结束专注，今天稍晚给你回复，可以吗？",
        ),
        DraftReply(
            tone="direct",
            label="直接",
            text="已收到。今天稍晚回复。",
        ),
    ]
    return drafts


def build_recovery_context(
    user_open_id: str,
    *,
    focus_start_ts: int,
    focus_end_ts: Optional[int] = None,
    period_summary: Optional[Dict[str, int]] = None,
    max_blocked: int = 5,
    include_drafts: bool = True,
) -> RecoveryContext:
    """主入口 1：把"挡到的消息 + AI 起草"组装成 RecoveryContext"""
    end_ts = focus_end_ts or int(time.time())
    duration = max(0, end_ts - focus_start_ts)

    blocked = collect_blocked_messages(
        user_open_id, focus_start_ts, max_n=max_blocked,
    )
    top = pick_top_message(blocked)
    drafts: List[DraftReply] = []
    explanation = ""

    if include_drafts and top is not None:
        drafts = draft_three_versions(user_open_id, top)
        explanation = (
            f"对最高优先级消息（{top.level} · {top.sender_name}）起草 3 版回复。"
            f" 选择 {top.level} 因为它在 {len(blocked)} 条挡掉的消息中得分最高（{top.score:.2f}）。"
        )

    return RecoveryContext(
        user_open_id=user_open_id,
        focus_duration_sec=duration,
        period_summary=dict(period_summary or {}),
        blocked=blocked,
        drafts_for_top=drafts,
        top_message=top,
        explanation=explanation,
    )


# ── 卡片渲染 ────────────────────────────────────────────────


def _level_emoji(level: str) -> str:
    return {"P0": "🔴", "P1": "🟠", "P2": "🟡", "P3": "⚪"}.get(level, "⚪")


def _fmt_duration(sec: int) -> str:
    if sec < 60:
        return f"{sec} 秒"
    if sec < 3600:
        return f"{sec // 60} 分钟"
    h = sec // 3600
    m = (sec % 3600) // 60
    return f"{h} 小时 {m} 分钟" if m else f"{h} 小时"


def render_recovery_card(ctx: RecoveryContext) -> Dict[str, Any]:
    """Build the Feishu interactive card JSON dict.

    See class-level docstring for layout. The output is a complete
    ``{"config": ..., "header": ..., "elements": [...]}`` dict that can
    be passed to ``bot.message_sender.send_card``.
    """

    # ── Header ────────────────────────────────────────────────
    header = {
        "title": {
            "tag": "plain_text",
            "content": f"🛡 LarkMentor · 上下文恢复 · 你专注了 {_fmt_duration(ctx.focus_duration_sec)}",
        },
        "template": "blue",
    }

    elements: List[Dict[str, Any]] = []

    # ── Top half: blocked messages ────────────────────────────
    if ctx.blocked:
        lines = ["**📥 我替你挡了什么**（按重要性排序）"]
        for m in ctx.blocked:
            lines.append(
                f"{_level_emoji(m.level)} **[{m.level}]** "
                f"`{m.sender_name}` · {m.relative_time()} · "
                f"{m.short_content(80)}"
            )
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "\n".join(lines)},
        })
    else:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "**📥 我替你挡了什么** · 这段时间没有需要你看的消息。"},
        })

    elements.append({"tag": "hr"})

    # ── Bottom half: drafts for the top message ───────────────
    if ctx.drafts_for_top and ctx.top_message:
        head_text = (
            f"**📝 我替你起草了回复**（针对 {_level_emoji(ctx.top_message.level)} "
            f"`{ctx.top_message.sender_name}`：{ctx.top_message.short_content(40)}）"
        )
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": head_text},
        })

        for d in ctx.drafts_for_top:
            cite_suffix = f"\n_引用：{d.citation}_" if d.citation else ""
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**v{1 + ['conservative', 'neutral', 'direct'].index(d.tone)} {d.label}**\n> {d.text}{cite_suffix}",
                },
            })

        # Action buttons: adopt v1/v2/v3 + ignore + detail
        actions = []
        for i, d in enumerate(ctx.drafts_for_top, start=1):
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": f"采纳 v{i} {d.label}"},
                "type": "primary" if i == 2 else "default",
                "value": {"action": "recovery_adopt", "tone": d.tone},
            })
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "全部忽略"},
            "type": "default",
            "value": {"action": "recovery_ignore"},
        })
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "为什么这条最高？"},
            "type": "default",
            "value": {"action": "recovery_explain"},
        })
        elements.append({"tag": "action", "actions": actions})
    else:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "**📝 我替你起草了回复** · 暂无需要回复的紧急消息，可以专注下一段工作了。"},
        })

    # ── Footer ────────────────────────────────────────────────
    elements.append({"tag": "hr"})
    explain_md = ctx.explanation or "卡片由 LarkMentor 自动生成。"
    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "lark_md",
            "content": f"🤖 LarkMentor · {explain_md} · 30 秒内可点撤回 · **永不自动发送**",
        }],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": header,
        "elements": elements,
    }


# ── 一键调用入口 ────────────────────────────────────────────


def send_recovery_card(
    user_open_id: str,
    *,
    focus_start_ts: int,
    focus_end_ts: Optional[int] = None,
    period_summary: Optional[Dict[str, int]] = None,
    max_blocked: int = 5,
    include_drafts: bool = True,
    sender=None,
) -> Tuple[bool, RecoveryContext]:
    """Build and send the Recovery Card to the user.

    The ``sender`` argument is optional and defaults to
    ``bot.message_sender.send_card`` so this function is testable
    without the Feishu SDK loaded.
    """
    ctx = build_recovery_context(
        user_open_id,
        focus_start_ts=focus_start_ts,
        focus_end_ts=focus_end_ts,
        period_summary=period_summary,
        max_blocked=max_blocked,
        include_drafts=include_drafts,
    )
    card = render_recovery_card(ctx)

    if sender is None:
        try:
            from bot.message_sender import send_card
            sender = send_card
        except Exception as e:
            logger.warning("recovery_card sender unavailable, returning context only: %s", e)
            return False, ctx

    ok = False
    try:
        ok = bool(sender(user_open_id, card))
    except Exception as e:
        logger.warning("send_recovery_card failed: %s", e)
        ok = False
    return ok, ctx
