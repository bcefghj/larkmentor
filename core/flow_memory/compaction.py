"""Compaction: collapse a batch of events into a markdown summary.

Inspired by Claude Code's wU2 three-tier compaction:

1. **Micro** – pure pattern collapse, no LLM call (cheap/instant).
2. **Session** – LLM-based summary at end of focus session.
3. **Full** – nightly digest that mixes the day's session summaries.

The summary is what the agent will load back as context next time the user
asks "what was I doing yesterday?" / "weekly report" etc.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .working import WorkingEvent

logger = logging.getLogger("flowguard.memory.compaction")


COMPACT_PROMPT = """\
你是 FlowGuard 的会话压缩器。把下面这段用户的工作流事件压缩成 ≤200 字的 markdown 摘要。

== 事件列表（按时间正序，每条 1 行）==
{events}

== 输出要求 ==
- 用第三人称、过去时
- 必须包含：主任务（1 句）、关键决策（≤3 条）、未完成块（≤3 条）、下一步建议（1 条）
- 输出纯 markdown，不要 JSON、不要前后缀

请直接输出摘要：
"""


@dataclass
class CompactionResult:
    """Output of one compaction call."""

    summary_md: str
    event_count: int
    span_seconds: int
    used_llm: bool = False
    metadata: Dict[str, str] = field(default_factory=dict)


# ── Tier 1: micro compaction (rule-based, no LLM) ──


def micro_compact(events: List[WorkingEvent]) -> CompactionResult:
    """Pure aggregation for tier-1 compaction."""
    if not events:
        return CompactionResult(summary_md="(空)", event_count=0, span_seconds=0)
    by_kind: Dict[str, int] = {}
    for e in events:
        by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
    span = events[-1].ts - events[0].ts if events else 0
    parts = [f"- **{k}**: {v} 条" for k, v in sorted(by_kind.items())]
    md = "## 自动汇总（无 LLM）\n\n" + "\n".join(parts)
    return CompactionResult(
        summary_md=md, event_count=len(events), span_seconds=span, used_llm=False,
    )


# ── Tier 2: session compaction (LLM) ──


def _format_event_line(ev: WorkingEvent) -> str:
    p = ev.payload or {}
    if ev.kind == "message":
        sender = p.get("sender_name", "?")
        level = p.get("level", "?")
        content = (p.get("content") or "")[:80]
        return f"[{ev.ts}] msg/{level} {sender}: {content}"
    if ev.kind == "decision":
        return f"[{ev.ts}] decision {p.get('action', '?')} score={p.get('score', '?')}"
    if ev.kind == "focus_start":
        return f"[{ev.ts}] focus_start ctx={p.get('context', '')}"
    if ev.kind == "focus_end":
        return f"[{ev.ts}] focus_end duration={p.get('duration_min', '')}min"
    return f"[{ev.ts}] {ev.kind} {str(p)[:80]}"


def session_compact(
    events: List[WorkingEvent],
    *,
    llm_chat=None,  # callable(prompt: str) -> str ; injected for testability
) -> CompactionResult:
    """LLM-backed compaction. Falls back to micro when LLM is unavailable."""
    if not events:
        return CompactionResult(summary_md="(空)", event_count=0, span_seconds=0)
    if llm_chat is None:
        try:
            from llm.llm_client import chat as llm_chat  # type: ignore
        except Exception:
            return micro_compact(events)
    lines = "\n".join(_format_event_line(e) for e in events[-120:])
    prompt = COMPACT_PROMPT.format(events=lines)
    try:
        out = llm_chat(prompt)
        if not out:
            return micro_compact(events)
        return CompactionResult(
            summary_md=out.strip(),
            event_count=len(events),
            span_seconds=events[-1].ts - events[0].ts,
            used_llm=True,
        )
    except Exception as e:
        logger.warning("session_compact LLM error: %s", e)
        return micro_compact(events)


def compact_session(
    events: List[WorkingEvent], *, tier: str = "auto", llm_chat=None,
) -> CompactionResult:
    """Public entry point. tier ∈ {micro, session, auto}.

    auto = micro when len(events) < 30 else session.
    """
    if tier == "micro":
        return micro_compact(events)
    if tier == "session":
        return session_compact(events, llm_chat=llm_chat)
    # auto
    if len(events) < 30:
        return micro_compact(events)
    return session_compact(events, llm_chat=llm_chat)
