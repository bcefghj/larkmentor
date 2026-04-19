"""Weekly report generator."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from core.flow_memory.archival import query_archival, write_archival_summary
from core.flow_memory.working import WorkingMemory

logger = logging.getLogger("flowguard.review.weekly")


WEEKLY_PROMPT = """\
你是 FlowGuard 周报生成器。基于用户最近 7 天的工作记忆，生成一份可以直接发给上级的周报。

== 用户基础信息 ==
{user_meta}

== 本周事件统计 ==
- 进入专注次数：{focus_count}
- 累计专注时长：{focus_minutes} 分钟
- P0 紧急消息：{p0}
- P1 重要消息：{p1}
- P2 已代回复：{p2}
- P3 已归档：{p3}

== 本周已沉淀的会话摘要（archival）==
{summaries}

== 输出要求 ==
- 用 markdown，分四节：本周完成、进行中、下周计划、需要协助
- 每节 3-5 个 bullet
- 总长 ≤ 350 字
- 第一人称、过去时
- 不要客套话、不要 emoji
- 不要泄露具体客户姓名/手机/邮箱（这些已经被脱敏）

请直接输出周报正文：
"""


@dataclass
class WeeklyReport:
    open_id: str
    week_start_ts: int
    week_end_ts: int
    body_md: str
    stats: Dict[str, int]
    used_llm: bool


def _collect_stats(open_id: str, since_ts: int) -> Dict[str, int]:
    stats = {"focus_count": 0, "focus_minutes": 0,
             "p0": 0, "p1": 0, "p2": 0, "p3": 0}
    try:
        wm = WorkingMemory.load(open_id)
        for ev in wm.since(since_ts):
            if ev.kind == "focus_start":
                stats["focus_count"] += 1
            elif ev.kind == "focus_end":
                stats["focus_minutes"] += int(ev.payload.get("duration_min", 0) or 0)
            elif ev.kind == "decision":
                lv = (ev.payload.get("level") or "").upper()
                key = lv.lower() if lv in {"P0", "P1", "P2", "P3"} else None
                if key:
                    stats[key] = stats.get(key, 0) + 1
    except Exception as e:
        logger.debug("weekly stats fallback: %s", e)
    return stats


def generate_weekly_report(
    open_id: str,
    *,
    user_meta: str = "",
    llm_chat: Optional[Callable[[str], str]] = None,
    publish: bool = True,
) -> WeeklyReport:
    """Build the weekly report. Always returns – never raises."""
    now = int(time.time())
    week_start = now - 7 * 86400

    stats = _collect_stats(open_id, week_start)
    archived = query_archival(open_id, since_ts=week_start, limit=50)
    summaries_md = (
        "\n\n".join(f"- ({a.kind}) {a.summary_md[:200]}" for a in archived)
        if archived else "（本周无 archival 摘要）"
    )

    if llm_chat is None:
        try:
            from llm.llm_client import chat as llm_chat  # type: ignore
        except Exception:
            llm_chat = None

    prompt = WEEKLY_PROMPT.format(
        user_meta=user_meta or open_id[-8:],
        focus_count=stats["focus_count"],
        focus_minutes=stats["focus_minutes"],
        p0=stats.get("p0", 0), p1=stats.get("p1", 0),
        p2=stats.get("p2", 0), p3=stats.get("p3", 0),
        summaries=summaries_md,
    )

    body_md = ""
    used_llm = False
    if llm_chat:
        try:
            body_md = llm_chat(prompt) or ""
            used_llm = bool(body_md)
        except Exception as e:
            logger.warning("weekly llm error: %s", e)

    if not body_md:
        body_md = (
            "## 本周周报（无 LLM · 自动汇总）\n\n"
            f"- 进入专注 {stats['focus_count']} 次，累计 {stats['focus_minutes']} 分钟\n"
            f"- 处理消息：P0 {stats['p0']} / P1 {stats['p1']} / P2 {stats['p2']} / P3 {stats['p3']}\n"
            f"- 沉淀的 archival 摘要 {len(archived)} 条\n"
        )

    report = WeeklyReport(
        open_id=open_id,
        week_start_ts=week_start,
        week_end_ts=now,
        body_md=body_md.strip(),
        stats=stats,
        used_llm=used_llm,
    )

    if publish:
        try:
            write_archival_summary(
                open_id, body_md, kind="weekly",
                span_start=week_start, span_end=now,
                meta={"used_llm": str(used_llm)},
            )
        except Exception as e:
            logger.warning("weekly publish skipped: %s", e)

    return report
