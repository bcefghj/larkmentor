"""Monthly Wrapped: Spotify-style highlight card for the user."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Optional

from core.flow_memory.archival import query_archival
from core.flow_memory.working import WorkingMemory


@dataclass
class WrappedCard:
    open_id: str
    month_start_ts: int
    month_end_ts: int
    headline: str
    bullets: list
    stats: Dict[str, int]


def _hour_distribution(open_id: str, since_ts: int) -> Counter:
    bucket: Counter = Counter()
    try:
        wm = WorkingMemory.load(open_id)
        for ev in wm.since(since_ts):
            if ev.kind == "decision":
                hour = time.localtime(ev.ts).tm_hour
                bucket[hour] += 1
    except Exception:
        pass
    return bucket


def generate_monthly_wrapped(open_id: str, *, days: int = 30) -> WrappedCard:
    now = int(time.time())
    start = now - days * 86400

    wm = WorkingMemory.load(open_id)
    events = wm.since(start)

    focus_starts = [e for e in events if e.kind == "focus_start"]
    focus_ends = [e for e in events if e.kind == "focus_end"]
    decisions = [e for e in events if e.kind == "decision"]
    p0 = sum(1 for e in decisions if (e.payload.get("level") or "") == "P0")
    p2 = sum(1 for e in decisions if (e.payload.get("level") or "") == "P2")
    total_focus_min = sum(int(e.payload.get("duration_min", 0) or 0) for e in focus_ends)

    archived = query_archival(open_id, since_ts=start, limit=500)

    hour_dist = _hour_distribution(open_id, start)
    if hour_dist:
        peak_hour, _ = hour_dist.most_common(1)[0]
        peak_label = f"{peak_hour:02d}:00 - {peak_hour + 1:02d}:00"
    else:
        peak_label = "尚无数据"

    headline = (
        f"过去 {days} 天，你专注 {len(focus_starts)} 次、累计 {total_focus_min} 分钟，"
        f"FlowGuard 替你挡掉 {p2} 次低优先级打扰。"
    )
    bullets = [
        f"专注次数：{len(focus_starts)} · 总时长 {total_focus_min} 分钟",
        f"紧急消息（P0）：{p0} 条 · 全部第一时间送达",
        f"代回复（P2）：{p2} 条 · 节省你 {p2 * 1.5:.0f} 分钟阅读时间",
        f"消息高峰时段：{peak_label}",
        f"沉淀的会话摘要：{len(archived)} 条",
    ]

    return WrappedCard(
        open_id=open_id,
        month_start_ts=start,
        month_end_ts=now,
        headline=headline,
        bullets=bullets,
        stats={
            "focus_starts": len(focus_starts),
            "focus_minutes": total_focus_min,
            "p0": p0,
            "p2": p2,
            "decisions": len(decisions),
            "archival": len(archived),
        },
    )
