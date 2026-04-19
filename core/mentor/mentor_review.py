"""Weekly report mentor · STAR + citations.

Builds on v3 ``work_review.weekly_report`` but enforces **STAR** structure
(Situation / Task / Action / Result) on every bullet and threads through
``[来源: archival_id_xxx]`` citations so the user can click back to the
underlying focus session, decision, or org doc.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List

from llm.llm_client import chat
from llm.prompts import MENTOR_REVIEW_STAR_PROMPT

from . import knowledge_base as kb

logger = logging.getLogger("flowguard.mentor.review")


@dataclass
class WeeklyDraft:
    open_id: str
    week_start_ts: int
    week_end_ts: int
    body_md: str = ""
    stats: Dict[str, int] = field(default_factory=dict)
    citations: List[str] = field(default_factory=list)
    used_llm: bool = False
    used_star: bool = False

    def to_dict(self) -> dict:
        return {
            "open_id": self.open_id,
            "week_start_ts": self.week_start_ts,
            "week_end_ts": self.week_end_ts,
            "body_md": self.body_md,
            "stats": self.stats,
            "citations": self.citations,
            "used_llm": self.used_llm,
            "used_star": self.used_star,
        }


def _collect_stats(open_id: str, since_ts: int) -> Dict[str, int]:
    stats = {"focus_count": 0, "focus_minutes": 0,
             "p0": 0, "p1": 0, "p2": 0, "p3": 0}
    try:
        from core.flow_memory.working import WorkingMemory

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
    except Exception as e:  # noqa: BLE001
        logger.debug("stats_fallback err=%s", e)
    return stats


def _has_star(text: str) -> bool:
    return all(tag in text for tag in ("[S]", "[T]", "[A]", "[R]"))


def draft(open_id: str, *, user_meta: str = "", week_offset: int = 0) -> WeeklyDraft:
    """Generate a STAR-formatted weekly draft. Always returns; never raises."""
    now = int(time.time())
    week_end = now - week_offset * 7 * 86400
    week_start = week_end - 7 * 86400

    stats = _collect_stats(open_id, week_start)

    archived: list = []
    try:
        from core.flow_memory.archival import query_archival

        archived = query_archival(open_id, since_ts=week_start, limit=50)
    except Exception as e:  # noqa: BLE001
        logger.debug("archival_fallback err=%s", e)

    summaries_md = (
        "\n\n".join(
            f"- archival_{getattr(a, 'id', i)} ({a.kind}) {a.summary_md[:200]}"
            for i, a in enumerate(archived)
        )
        if archived else "（本周无 archival 摘要）"
    )

    org_hits = kb.search(open_id, "周报 风格 模板")
    org_context = kb.render_citations(org_hits) if org_hits else "（无组织文档）"

    prompt = MENTOR_REVIEW_STAR_PROMPT.format(
        user_meta=user_meta or open_id[-8:],
        focus_count=stats["focus_count"],
        focus_minutes=stats["focus_minutes"],
        p0=stats["p0"], p1=stats["p1"], p2=stats["p2"], p3=stats["p3"],
        summaries=summaries_md,
        org_context=org_context,
    )

    body = ""
    used_llm = False
    try:
        body = chat(prompt, temperature=0.3) or ""
        used_llm = bool(body.strip())
    except Exception as e:  # noqa: BLE001
        logger.warning("weekly_llm_fail err=%s", e)

    if not body:
        body = (
            "## 本周周报（无 LLM · 自动汇总）\n\n"
            f"- [S] 本周 [T] 进入专注 [A] {stats['focus_count']} 次 "
            f"[R] 累计 {stats['focus_minutes']} 分钟 [来源: 待补充]\n"
            f"- [S] 本周消息 [T] 分流处理 [A] FlowGuard "
            f"[R] P0 {stats['p0']} / P1 {stats['p1']} / P2 {stats['p2']} / P3 {stats['p3']} "
            f"[来源: 待补充]\n"
        )

    citations = [
        f"archival_{getattr(a, 'id', i)}"
        for i, a in enumerate(archived)
    ]

    return WeeklyDraft(
        open_id=open_id,
        week_start_ts=week_start,
        week_end_ts=week_end,
        body_md=body.strip(),
        stats=stats,
        citations=citations,
        used_llm=used_llm,
        used_star=_has_star(body),
    )
